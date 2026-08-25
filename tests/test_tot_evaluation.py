"""ToT state evaluators (ADR 0011): value and vote, repeated and aggregated (REQ-6/7/8).

These drive the evaluators with a scripted cold ``ModelClient`` -- no real model -- and assert the
aggregation contract: ``value`` averages its repeated scores and flags dead ends below the threshold;
``vote`` Borda-aggregates repeated rankings; ties resolve deterministically; both respect the call
budget.
"""

from __future__ import annotations

from collections.abc import Sequence

from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec
from videogen.agent.tot.controller import CallBudget, ThoughtState
from videogen.agent.tot.evaluation import make_value_evaluator, make_vote_evaluator


class QueueClient:
    """Returns queued reply texts in order; repeats the last once drained."""

    model = "fake"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.calls += 1
        text = self._replies.pop(0) if self._replies else "{}"
        return AssistantTurn(text=text)


class FixedClient:
    model = "fake"

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def next_turn(self, *, system, history, tools) -> AssistantTurn:  # type: ignore[no-untyped-def]
        self.calls += 1
        return AssistantTurn(text=self._text)


def _state() -> ThoughtState:
    return ThoughtState()


# -- value --------------------------------------------------------------------------------------

def test_value_averages_repeated_scores() -> None:
    client = QueueClient(['{"score": 4}', '{"score": 2}', '{"score": 3}'])
    evaluate = make_value_evaluator(
        client=client,
        system="score it",
        render_candidate=lambda c: str(c),
        n_evaluate=3,
        dead_end_threshold=3.0,
    )
    [scored] = evaluate(_state(), ["cand"], CallBudget(10))

    assert scored.score == 3.0  # (4 + 2 + 3) / 3
    assert scored.dead_end is False  # 3.0 is not below the 3.0 threshold


def test_value_flags_dead_end_below_threshold() -> None:
    client = QueueClient(['{"score": 1}', '{"score": 2}', '{"score": 1}'])
    evaluate = make_value_evaluator(
        client=client,
        system="score it",
        render_candidate=lambda c: str(c),
        n_evaluate=3,
        dead_end_threshold=3.0,
    )
    [scored] = evaluate(_state(), ["weak"], CallBudget(10))

    assert round(scored.score, 2) == 1.33
    assert scored.dead_end is True


def test_value_respects_the_call_budget() -> None:
    client = QueueClient(['{"score": 5}'] * 10)
    evaluate = make_value_evaluator(
        client=client,
        system="score it",
        render_candidate=lambda c: str(c),
        n_evaluate=3,
        dead_end_threshold=3.0,
    )
    budget = CallBudget(2)  # only 2 calls allowed across all candidates/samples
    evaluate(_state(), ["a", "b"], budget)

    assert client.calls == 2
    assert budget.exhausted is True


# -- vote ---------------------------------------------------------------------------------------

def test_vote_borda_aggregates_repeated_rankings() -> None:
    client = FixedClient('{"ranking": [0, 1, 2]}')
    evaluate = make_vote_evaluator(
        client=client,
        system="rank them",
        render_candidate=lambda c: str(c),
        n_evaluate=3,
    )
    scored = evaluate(_state(), ["x", "y", "z"], CallBudget(10))
    by_thought = {s.thought: s.score for s in scored}

    # Borda per ballot: index 0 -> 3, 1 -> 2, 2 -> 1; summed over 3 ballots.
    assert by_thought["x"] == 9.0
    assert by_thought["y"] == 6.0
    assert by_thought["z"] == 3.0


def test_vote_ties_resolve_deterministically() -> None:
    # Two ballots that exactly mirror each other -> equal Borda totals.
    client = QueueClient(['{"ranking": [0, 1]}', '{"ranking": [1, 0]}'])
    evaluate = make_vote_evaluator(
        client=client,
        system="rank them",
        render_candidate=lambda c: str(c),
        n_evaluate=2,
    )
    scored = evaluate(_state(), ["p", "q"], CallBudget(10))

    assert scored[0].score == scored[1].score == 3.0  # each: (2 + 1)
