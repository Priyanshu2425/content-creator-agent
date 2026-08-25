"""CreativeDirectionToTAgent (ADR 0011): the Tree-of-Thoughts variant of the creative-direction worker.

Like ``test_text_hook_tot.py``, these script a fake ``ModelClient`` (routing by system prompt, and by
payload where a stage must distinguish branches) and assert the worker's contract: it searches a
concept -> execution tree and returns the single winning direction string, it degrades to an honest
message when output is unusable, and a concept whose execution fails the brand / 'show, don't tell'
constraint is rejected (dead-ended) rather than returned.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from videogen.agent.creative_direction_tot import _NO_DIRECTION, CreativeDirectionToTAgent
from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec
from videogen.agent.tot.config import ToTConfig


class RoutedClient:
    """Routes by system prompt; ``exec_for``/``score_for`` inspect the payload so a stage can branch
    per concept. Same instance serves as hot (generation) and cold (evaluation)."""

    model = "fake"

    def __init__(self, *, concepts, exec_for, score_for, ranking='{"ranking":[0,1]}') -> None:
        self._concepts = itertools.cycle(concepts)
        self._exec_for = exec_for
        self._score_for = score_for
        self._ranking = ranking
        self.seen: list[str] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        payload = history[-1].text if history else ""
        self.seen.append(payload)
        if "commit to ONE creative concept" in system:
            return AssistantTurn(text=next(self._concepts))
        if "expand the chosen concept" in system:
            return AssistantTurn(text=self._exec_for(payload))
        if "scoring a single" in system:  # value evaluator (concept or execution gate)
            return AssistantTurn(text=f'{{"score": {self._score_for(payload)}}}')
        if "Rank" in system or "editor" in system:
            return AssistantTurn(text=self._ranking)
        return AssistantTurn(text="")


_GOOD_CONCEPT = '{"label":"c1","core_message":"speed wins","metaphor":"a stopwatch","rationale":"r"}'


def test_returns_a_single_winning_direction_string() -> None:
    client = RoutedClient(
        concepts=[_GOOD_CONCEPT],
        exec_for=lambda p: "DIRECTION: open on a concrete stopwatch shot, then cut to the workflow.",
        score_for=lambda p: 4,
    )
    cfg = ToTConfig(max_depth=2, n_generate_sample=1, breadth_limit=2, n_evaluate_sample=1)
    agent = CreativeDirectionToTAgent(hot_client=client, cold_client=client, config=cfg)

    direction = agent.generate(brief="promote a fast editing tool", transcript="we make editing fast")

    assert isinstance(direction, str)
    assert "DIRECTION" in direction
    assert direction != _NO_DIRECTION


def test_degrades_to_honest_message_when_output_is_unusable() -> None:
    client = RoutedClient(concepts=[""], exec_for=lambda p: "", score_for=lambda p: 1)
    cfg = ToTConfig(max_depth=2, n_generate_sample=2, breadth_limit=2, n_evaluate_sample=1)
    agent = CreativeDirectionToTAgent(hot_client=client, cold_client=client, config=cfg)

    direction = agent.generate(brief="x", transcript="y")

    assert direction == _NO_DIRECTION


def test_execution_failing_the_brand_constraint_is_rejected() -> None:
    # Two concepts survive the concept gate; the 'weak' concept's execution stays abstract (scores
    # below threshold -> dead end), the 'strong' concept's execution is concrete. The winning
    # direction must be the strong one, not the higher-... -- the dead end is pruned, not returned.
    def exec_for(payload: str) -> str:
        if "[strong]" in payload:
            return "STRONG_DIRECTION: open on a concrete stopwatch; every beat names a real shot."
        return "WEAK_DIRECTION: keep it abstract and vibey, no concrete shots."

    def score_for(payload: str) -> int:
        if "WEAK_DIRECTION" in payload:
            return 1  # fails the show-don't-tell constraint -> below threshold -> dead end
        if "STRONG_DIRECTION" in payload:
            return 5
        return 4  # both concepts pass the concept gate

    client = RoutedClient(
        concepts=[
            '{"label":"weak","core_message":"m","metaphor":"vibes","rationale":"r"}',
            '{"label":"strong","core_message":"m","metaphor":"a stopwatch","rationale":"r"}',
        ],
        exec_for=exec_for,
        score_for=score_for,
    )
    # value at BOTH gates makes the execution dead-end deterministic.
    cfg = ToTConfig(
        method_evaluate="value",
        search_algorithm="bfs",
        max_depth=2,
        n_generate_sample=2,
        breadth_limit=2,
        n_evaluate_sample=1,
        dead_end_threshold=3.0,
    )
    agent = CreativeDirectionToTAgent(hot_client=client, cold_client=client, config=cfg)

    direction = agent.generate(brief="promote a tool", transcript="t")

    assert "STRONG_DIRECTION" in direction
    assert "WEAK" not in direction
