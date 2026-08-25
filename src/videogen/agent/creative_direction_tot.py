"""CreativeDirectionToTAgent: the Tree-of-Thoughts variant of the creative-direction worker (ADR 0011).

A deliberating sibling of ``CreativeDirectionAgent`` (legacy, untouched). It searches a depth-2 tree
-- **creative concept -> execution** -- generating competing concepts, pruning weak ones, expanding
the survivors into a full beat-by-beat direction, and returning the *single winning direction*
document (REQ-12) the Director already consumes as a string. The generic ToT core (controller,
generator, evaluator) is reused verbatim; only the prompts, parsing, and leaf shaping live here.

Runs on Gemini only: a hot client (diverse generation) and a cold client (stable evaluation). The
Director's dispatch contract is unchanged -- one dispatch still returns one direction string.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from videogen import log, tracing
from videogen.agent.model import ModelClient
from videogen.agent.tot.config import ToTConfig
from videogen.agent.tot.controller import Evaluator, Stage, ToTController
from videogen.agent.tot.evaluation import make_value_evaluator, make_vote_evaluator
from videogen.agent.tot.generation import make_sample_generator

_CONCEPT_SYSTEM = """\
You are a Lead Creative Director. Read the brief and transcript and commit to ONE creative concept
for a short-form video -- the governing visual strategy the whole edit will answer to. A concept is a
core message plus ONE concrete visual metaphor (never abstract: a scene, an object, a treatment).
Several legitimate concepts exist per transcript; pick exactly one and frame it. Do not write the
beat-by-beat execution yet.

Return only JSON, no prose:
{"label": "<short name>", "core_message": "<one sentence>",
 "metaphor": "<the concrete visual metaphor>", "rationale": "<why it fits the brief/transcript>"}
"""

_EXECUTION_SYSTEM = """\
You are a Lead Creative Director. Given a chosen creative concept, expand the chosen concept into a
full beat-by-beat direction: the opening hook (first 3s), a beat-by-beat B-roll map ('show, don't
tell' -- every abstract idea gets a concrete visual), pacing notes, and a CTA. Every beat must name a
concrete visual; if a beat cannot be made concrete, say so rather than staying abstract.

Return the direction as readable prose/markdown (no JSON). Be specific enough to hand to an editor.
"""

_VOTE_SYSTEM = """\
You are a Creative Director's editor. You are given competing candidates for one stage of a video's
creative direction. Judge them on strategic strength, concreteness ('show, don't tell'), retention,
and brand fit. Rank them best-to-worst.
"""

_CONCEPT_VALUE_SYSTEM = """\
You are scoring a single creative concept in isolation: how well the transcript and brief support it,
and how distinct/non-generic it is. A concept the material barely supports, or a generic one, scores
low.
"""

_EXECUTION_VALUE_SYSTEM = """\
You are scoring a single execution in isolation on brand alignment and the 'show, don't tell'
mandate: does every abstract beat translate into a CONCRETE visual? An execution that stays abstract,
ignores the brand, or cannot make its beats concrete scores low -- it is a dead end.
"""

_NO_DIRECTION = (
    "No usable creative direction could be generated from the brief and transcript. "
    "Author direction manually rather than relying on a fabricated concept."
)


@dataclass(frozen=True)
class _Concept:
    label: str
    core_message: str
    metaphor: str
    rationale: str = ""


class CreativeDirectionToTAgent:
    """Produces a single winning creative direction by searching a concept -> execution tree."""

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
        brief: str,
        transcript: str,
        brand_kit: dict[str, Any] | None = None,
        scratchpad: str = "",
        guidance: str = "",
    ) -> str:
        ctx = _Context(
            brief=brief,
            transcript=transcript,
            brand_kit=brand_kit,
            scratchpad=scratchpad,
            guidance=guidance,
        )
        stages = self._build_stages(ctx)

        with tracing.agent_span("creative-direction-tot-agent", input_summary={"guidance": guidance}):
            result = ToTController(self._config).search(stages)
            _log_tree("CreativeDirectionToTAgent", result)

        winning = result.best[1].thought if result.best is not None else None
        log.get().agent_event_complete("CreativeDirectionToTAgent", duration_ms=0)
        if not isinstance(winning, str) or not winning.strip():
            return _NO_DIRECTION
        return winning

    def _build_stages(self, ctx: _Context) -> list[Stage]:
        cfg = self._config
        concept_gen = make_sample_generator(
            client=self._hot,
            system=_CONCEPT_SYSTEM,
            build_payload=lambda _state: ctx.concept_payload(),
            parse=lambda text, _state: _parse_concept(text),
            k=cfg.n_generate_sample,
        )
        concept_eval = self._evaluator(
            gate="frame",
            value_system=_CONCEPT_VALUE_SYSTEM,
            vote_system=_VOTE_SYSTEM,
            render_candidate=lambda c: f"concept [{c.label}]: {c.core_message} | metaphor: {c.metaphor}",
            vote_intro="Rank these creative concepts by strategic strength.",
        )
        execution_gen = make_sample_generator(
            client=self._hot,
            system=_EXECUTION_SYSTEM,
            build_payload=lambda state: ctx.execution_payload(state.last),
            parse=lambda text, _state: _parse_execution(text),
            k=cfg.n_generate_sample,
        )
        execution_eval = self._evaluator(
            gate="execution",
            value_system=_EXECUTION_VALUE_SYSTEM,
            vote_system=_VOTE_SYSTEM,
            render_candidate=lambda d: _truncate(d),
            vote_intro="Rank these full directions by strategic strength and concreteness.",
        )
        return [
            Stage(name="creative-concept", generate=concept_gen, evaluate=concept_eval, keep=cfg.breadth_limit),
            Stage(name="execution", generate=execution_gen, evaluate=execution_eval, keep=None),
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
        ``vote`` use that strategy at every gate; ``hybrid`` (default) scores concepts by value and
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
    brief: str
    transcript: str
    brand_kit: dict[str, Any] | None
    scratchpad: str
    guidance: str

    def _common(self) -> list[str]:
        parts: list[str] = []
        if self.guidance:
            parts.append(f"Focus: {self.guidance}")
        parts.append(f"Brief:\n{self.brief}")
        if self.brand_kit:
            parts.append(f"Brand kit tokens:\n{json.dumps(self.brand_kit, indent=2)}")
        if self.scratchpad and self.scratchpad.strip() != "(scratchpad is empty)":
            parts.append(f"Director's current thinking:\n{self.scratchpad}")
        return parts

    def concept_payload(self) -> str:
        return "\n\n".join([*self._common(), f"Transcript:\n{self.transcript}"])

    def execution_payload(self, concept: _Concept) -> str:
        return "\n\n".join(
            [
                *self._common(),
                f"Chosen concept [{concept.label}]: {concept.core_message}",
                f"Visual metaphor: {concept.metaphor}",
                f"Transcript:\n{self.transcript}",
            ]
        )


def _gemini(model: str, temperature: float) -> ModelClient:
    from videogen.agent.clients.gemini import GeminiModelClient

    return GeminiModelClient(model=model, temperature=temperature)


def _parse_concept(text: str) -> _Concept | None:
    data = _extract_json(text)
    if not data:
        return None
    core = str(data.get("core_message", "")).strip()
    metaphor = str(data.get("metaphor", "")).strip()
    if not core or not metaphor:
        return None
    return _Concept(
        label=str(data.get("label", "concept")).strip() or "concept",
        core_message=core,
        metaphor=metaphor,
        rationale=str(data.get("rationale", "")).strip(),
    )


def _parse_execution(text: str) -> str | None:
    """The execution thought is the full direction document. Empty/blank output is unusable (a dead
    end is the evaluator's job; here we only drop genuinely empty completions)."""
    cleaned = (text or "").strip()
    return cleaned or None


def _truncate(text: str, limit: int = 1200) -> str:
    return text if len(text) <= limit else text[:limit] + " […]"


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
