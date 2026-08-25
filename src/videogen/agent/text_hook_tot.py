"""TextHookToTAgent: the Tree-of-Thoughts variant of the text-hook worker (ADR 0011).

A deliberating sibling of ``TextHookAgent`` (legacy, untouched). It searches a depth-2 tree --
**payoff frame -> hook phrasing** -- generating competing frames, pruning weak ones, expanding the
survivors into hooks, and returning the *same* ``HookProposal`` the Director already consumes. The
search controller, generator, and evaluator are the generic ToT core; only the prompts, the parsing,
and the leaf-to-proposal shaping live here.

Runs on Gemini only: it holds a hot client (diverse generation) and a cold client (stable
evaluation). The Director's dispatch contract is unchanged -- one dispatch still returns one
``HookProposal``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from videogen import log, tracing
from videogen.agent.model import ModelClient
from videogen.agent.text_hook import (
    _PATTERNS,
    HookCandidate,
    HookProposal,
    _fallback,
)
from videogen.agent.tot.config import ToTConfig
from videogen.agent.tot.controller import Evaluator, Stage, ToTController
from videogen.agent.tot.evaluation import make_value_evaluator, make_vote_evaluator
from videogen.agent.tot.generation import make_sample_generator

_FRAME_SYSTEM = """\
You are HookSmith's strategist. Read the transcript and commit to ONE interpretation of the video's
*payoff* -- what the viewer actually gets by watching. Most transcripts support several: a literal/
practical payoff, an emotional/identity payoff, or a contrarian/myth-busting payoff. Pick exactly one
and frame it. Do not write the on-screen hook yet.

Return only JSON, no prose:
{"label": "<literal|emotional|contrarian|...>", "payoff": "<one sentence: what the viewer gets>",
 "rationale": "<why the transcript supports this and how it differs from the spoken hook>"}
"""

_PHRASING_SYSTEM = """\
You are HookSmith. Given a chosen payoff frame, write ONE on-screen text hook for the first 1-3
seconds of a talking-head video -- a static headline for the muted scroller, a different angle from
the spoken hook. Constraints: <= 12 words (aim <= 8), sentence case (never ALL CAPS), no fabricated
claims or fake urgency, distinct from a plain transcript of the spoken line.

Name which pattern it uses (one of: reinforce, complement, curiosity_gap, audience_callout,
contradiction). Return only JSON, no prose:
{"text": "<the headline>", "pattern": "<one pattern>", "rationale": "<why it stops a muted scroller>"}
"""

_VOTE_SYSTEM = """\
You are HookSmith's editor. You are given competing candidates for one stage of a short-form video's
text hook. Judge them only by scroll-stopping power for a muted viewer: specificity, tension/
curiosity, audience fit, and freshness relative to a generic opening. Rank them best-to-worst.
"""

_FRAME_VALUE_SYSTEM = """\
You are HookSmith's editor scoring a single payoff frame in isolation. Score it on how directly the
transcript supports this interpretation AND how distinct it is from the spoken hook's own framing. A
frame the transcript barely supports, or that merely restates the spoken line, scores low.
"""

_HOOK_VALUE_SYSTEM = """\
You are HookSmith's editor scoring a single text hook in isolation on scroll-stopping power for a
muted viewer: specificity, tension/curiosity, audience fit, and freshness. A vague or generic hook
scores low.
"""


@dataclass(frozen=True)
class _Frame:
    label: str
    payoff: str
    rationale: str = ""


class TextHookToTAgent:
    """Generates ranked text-hook candidates by searching a payoff-frame -> phrasing tree."""

    def __init__(
        self,
        *,
        hot_client: ModelClient | None = None,
        cold_client: ModelClient | None = None,
        config: ToTConfig | None = None,
        model: str = "gemini-2.5-flash",
    ) -> None:
        self._config = config or ToTConfig()
        self._hot = hot_client or _gemini(model, self._config.hot_temperature)
        self._cold = cold_client or _gemini(model, self._config.cold_temperature)

    def generate(
        self,
        *,
        transcript: str,
        goal: str = "organic",
        audience: str = "",
        brand_kit: dict[str, Any] | None = None,
        n_variants: int = 5,
    ) -> HookProposal:
        ctx = _Context(transcript=transcript, goal=goal, audience=audience, brand_kit=brand_kit)
        stages = self._build_stages(ctx)

        with tracing.agent_span("text-hook-tot-agent", input_summary={"goal": goal}):
            result = ToTController(self._config).search(stages)
            _log_tree("TextHookToTAgent", result)

        leaves = [sc.thought for _, sc in result.leaves if isinstance(sc.thought, HookCandidate)]
        if not leaves:
            return _fallback()
        proposal = _select(leaves, n_variants)
        log.get().agent_event_complete(
            "TextHookToTAgent", duration_ms=0, candidates=len(proposal.candidates)
        )
        return proposal

    def _build_stages(self, ctx: _Context) -> list[Stage]:
        cfg = self._config
        frame_gen = make_sample_generator(
            client=self._hot,
            system=_FRAME_SYSTEM,
            build_payload=lambda _state: ctx.frame_payload(),
            parse=lambda text, _state: _parse_frame(text),
            k=cfg.n_generate_sample,
        )
        frame_eval = self._evaluator(
            gate="frame",
            value_system=_FRAME_VALUE_SYSTEM,
            vote_system=_VOTE_SYSTEM,
            render_candidate=lambda f: f"payoff frame [{f.label}]: {f.payoff}",
            vote_intro="Rank these payoff frames by how strong a hook each could yield.",
        )
        phrasing_gen = make_sample_generator(
            client=self._hot,
            system=_PHRASING_SYSTEM,
            build_payload=lambda state: ctx.phrasing_payload(state.last),
            parse=lambda text, _state: _parse_hook(text),
            k=cfg.n_generate_sample,
        )
        phrasing_eval = self._evaluator(
            gate="execution",
            value_system=_HOOK_VALUE_SYSTEM,
            vote_system=_VOTE_SYSTEM,
            render_candidate=lambda h: f'"{h.text}" [{h.pattern}]',
            vote_intro="Rank these text hooks by scroll-stopping power.",
        )
        return [
            Stage(name="payoff-frame", generate=frame_gen, evaluate=frame_eval, keep=cfg.breadth_limit),
            Stage(name="hook-phrasing", generate=phrasing_gen, evaluate=phrasing_eval, keep=None),
        ]

    def _evaluator(
        self,
        *,
        gate: str,
        value_system: str,
        vote_system: str,
        render_candidate: Any,
        vote_intro: str,
    ) -> Evaluator:
        """Pick the evaluator strategy for a gate from ``method_evaluate`` (PRD §3): ``value`` and
        ``vote`` use that strategy at every gate; ``hybrid`` (default) scores frames by value and
        ranks executions by vote."""
        cfg = self._config
        use_value = cfg.method_evaluate == "value" or (
            cfg.method_evaluate == "hybrid" and gate == "frame"
        )
        if use_value:
            return make_value_evaluator(
                client=self._cold,
                system=value_system,
                render_candidate=render_candidate,
                n_evaluate=cfg.n_evaluate_sample,
                dead_end_threshold=cfg.dead_end_threshold,
            )
        return make_vote_evaluator(
            client=self._cold,
            system=vote_system,
            render_candidate=render_candidate,
            n_evaluate=cfg.n_evaluate_sample,
            intro=vote_intro,
        )


@dataclass(frozen=True)
class _Context:
    transcript: str
    goal: str
    audience: str
    brand_kit: dict[str, Any] | None

    def _common(self) -> list[str]:
        parts = [f"goal: {self.goal}", f"audience: {self.audience or 'infer from the transcript'}"]
        if self.brand_kit:
            parts.append(f"brand_kit: {json.dumps(self.brand_kit)}")
        return parts

    def frame_payload(self) -> str:
        return "\n".join([*self._common(), "transcript:\n" + self.transcript])

    def phrasing_payload(self, frame: _Frame) -> str:
        return "\n".join(
            [
                *self._common(),
                f"chosen payoff frame [{frame.label}]: {frame.payoff}",
                f"frame rationale: {frame.rationale}",
                "transcript:\n" + self.transcript,
            ]
        )


def _gemini(model: str, temperature: float) -> ModelClient:
    from videogen.agent.clients.gemini import GeminiModelClient

    return GeminiModelClient(model=model, temperature=temperature)


def _parse_frame(text: str) -> _Frame | None:
    data = _extract_json(text)
    if not data or not str(data.get("payoff", "")).strip():
        return None
    return _Frame(
        label=str(data.get("label", "frame")).strip() or "frame",
        payoff=str(data["payoff"]).strip(),
        rationale=str(data.get("rationale", "")).strip(),
    )


def _parse_hook(text: str) -> HookCandidate | None:
    data = _extract_json(text)
    if not data or not str(data.get("text", "")).strip():
        return None
    pattern = str(data.get("pattern", "reinforce"))
    if pattern not in _PATTERNS:
        pattern = "reinforce"
    return HookCandidate(
        rank=0,  # assigned during selection
        text=str(data["text"]).strip(),
        pattern=pattern,
        rationale=str(data.get("rationale", "")).strip(),
    )


def _select(leaves: list[HookCandidate], n_variants: int) -> HookProposal:
    """Pick up to ``n_variants`` from the leaves (already score-ordered) while covering >= 3 patterns
    when the pool allows (PRD: never five variants of one pattern)."""
    chosen: list[HookCandidate] = []
    used_patterns: set[str] = set()
    # First pass: one per new pattern, to seed diversity.
    for cand in leaves:
        if len(chosen) >= n_variants:
            break
        if cand.pattern not in used_patterns:
            chosen.append(cand)
            used_patterns.add(cand.pattern)
    # Second pass: fill remaining slots by score order.
    for cand in leaves:
        if len(chosen) >= n_variants:
            break
        if cand not in chosen:
            chosen.append(cand)
    ranked = tuple(
        HookCandidate(rank=i, text=c.text, pattern=c.pattern, rationale=c.rationale)
        for i, c in enumerate(chosen, start=1)
    )
    return HookProposal(candidates=ranked, recommended=1)


def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _log_tree(agent: str, result: Any) -> None:
    """Log the full search tree for offline debugging (REQ-11), independent of the lean proposal."""
    try:
        for node in result.trace:
            log.get().agent_event_start(
                agent,
                stage=node.stage,
                candidates=len(node.scored),
                kept=len(node.kept),
                pruned=len(node.pruned_dead_ends),
            )
    except Exception:  # logging must never break a dispatch
        pass
