"""State evaluation for ToT stages (PRD §3, REQ-6/7/8).

Evaluation always runs on the *cold* client and on a separate call from generation, so no completion
grades its own output (REQ-7). Two strategies; this slice implements ``vote``:

- ``value`` -- score each candidate independently on a 1-5 scale; repeat ``n_evaluate`` times and
  average. A candidate whose average falls below ``dead_end_threshold`` is marked a dead end. Use
  when a candidate can be judged in isolation (the paper's Game-of-24 strategy; here, payoff frames
  against the transcript).
- ``vote`` -- show all candidates together and have the model rank them; repeat ``n_evaluate`` times
  and aggregate with Borda points (a candidate scores ``n-position`` per ballot). Use when quality is
  only meaningful comparatively (open-ended writing). The paper's Creative Writing strategy.

Both run on the cold client, separate from generation (REQ-7). Every model call is gated by the
shared ``CallBudget``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from videogen.agent.model import ModelClient, UserMessage
from videogen.agent.tot.controller import CallBudget, Evaluator, Scored, ThoughtState


def make_value_evaluator(
    *,
    client: ModelClient,
    system: str,
    render_candidate: Callable[[Any], str],
    n_evaluate: int,
    dead_end_threshold: float,
    scale: tuple[int, int] = (1, 5),
) -> Evaluator:
    """Build a ``value`` evaluator: each candidate scored independently, repeated and averaged.

    A candidate whose averaged score falls below ``dead_end_threshold`` is flagged ``dead_end`` so the
    controller can prune it (BFS) or backtrack past it (DFS)."""

    lo, hi = scale

    def evaluate(
        state: ThoughtState, candidates: list[Any], budget: CallBudget
    ) -> list[Scored]:
        out: list[Scored] = []
        for c in candidates:
            samples: list[float] = []
            for _ in range(n_evaluate):
                if not budget.try_spend(1):
                    break
                payload = _render_value_prompt(render_candidate(c), lo, hi)
                turn = client.next_turn(system=system, history=[UserMessage(payload)], tools=[])
                score = _parse_score(turn.text or "", lo, hi)
                if score is not None:
                    samples.append(score)
            avg = sum(samples) / len(samples) if samples else float(lo)
            out.append(
                Scored(
                    thought=c,
                    score=avg,
                    dead_end=avg < dead_end_threshold,
                    meta={"samples": len(samples)},
                )
            )
        return out

    return evaluate


def make_vote_evaluator(
    *,
    client: ModelClient,
    system: str,
    render_candidate: Callable[[Any], str],
    n_evaluate: int,
    intro: str = "Rank the following candidates best-to-worst for the stated goal.",
) -> Evaluator:
    """Build a ``vote`` evaluator: candidates ranked together, repeated and Borda-aggregated."""

    def evaluate(
        state: ThoughtState, candidates: list[Any], budget: CallBudget
    ) -> list[Scored]:
        n = len(candidates)
        if n == 0:
            return []
        if n == 1:
            return [Scored(thought=candidates[0], score=1.0)]
        tallies = [0.0] * n
        ballots = 0
        for _ in range(n_evaluate):
            if not budget.try_spend(1):
                break
            payload = _render_ballot(intro, candidates, render_candidate)
            turn = client.next_turn(system=system, history=[UserMessage(payload)], tools=[])
            ranking = _parse_ranking(turn.text or "", n)
            if not ranking:
                continue
            ballots += 1
            for position, idx in enumerate(ranking):
                tallies[idx] += float(n - position)
        if ballots == 0:
            # No usable ballots -- fall back to neutral equal scores so the search still proceeds.
            return [Scored(thought=c, score=0.0) for c in candidates]
        return [Scored(thought=c, score=tallies[i]) for i, c in enumerate(candidates)]

    return evaluate


def _render_value_prompt(candidate_text: str, lo: int, hi: int) -> str:
    return (
        f"Candidate:\n{candidate_text}\n\n"
        f"Score it from {lo} (weakest) to {hi} (strongest) against the criteria in your instructions. "
        'Return only JSON: {"score": <number>}.'
    )


def _parse_score(text: str, lo: int, hi: int) -> float | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "score" in data:
                return _clamp(float(data["score"]), lo, hi)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    num = re.search(r"-?\d+(?:\.\d+)?", text)
    if num:
        try:
            return _clamp(float(num.group(0)), lo, hi)
        except ValueError:
            return None
    return None


def _clamp(x: float, lo: int, hi: int) -> float:
    return max(float(lo), min(float(hi), x))


def _render_ballot(
    intro: str, candidates: list[Any], render_candidate: Callable[[Any], str]
) -> str:
    lines = [intro, ""]
    for i, c in enumerate(candidates):
        lines.append(f"[{i}] {render_candidate(c)}")
    lines.append("")
    lines.append(
        'Return only JSON: {"ranking": [<candidate indices, best first>]}. '
        "Include every index exactly once."
    )
    return "\n".join(lines)


def _parse_ranking(text: str, n: int) -> list[int]:
    """Parse a best-first ranking of 0-based indices. Tolerant of chatty replies and 1-based lists.

    Returns a de-duplicated, in-range ranking; missing indices are appended in order so the result is
    always a full permutation (a partial ranking still yields usable Borda scores)."""
    indices = _extract_indices(text)
    seen: list[int] = []
    for raw in indices:
        idx = raw
        if idx not in range(n) and (raw - 1) in range(n):
            idx = raw - 1  # tolerate 1-based rankings
        if idx in range(n) and idx not in seen:
            seen.append(idx)
    if not seen:
        return []
    for i in range(n):
        if i not in seen:
            seen.append(i)
    return seen


def _extract_indices(text: str) -> list[int]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            ranking = data.get("ranking") if isinstance(data, dict) else None
            if isinstance(ranking, list):
                return [int(x) for x in ranking if isinstance(x, (int, float))]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    # Fallback: first bracketed list of numbers anywhere in the text.
    arr = re.search(r"\[([\d,\s]+)\]", text)
    if arr:
        return [int(x) for x in re.findall(r"\d+", arr.group(1))]
    return []
