"""CreativeDirectionAgent emits a typed BeatPlan (ADR 0012, beat-plan/01).

The worker's reasoning is unchanged; only the delivery tightens from prose to a machine-readable
BeatPlan the Director executes by binding. These tests script a fake ModelClient and assert the
contract: generate() returns a parsed BeatPlan (tolerating a ```json fence and trailing prose), and
the legacy generate_prose() still returns plain text for the flag-off fallback.
"""

from __future__ import annotations

from collections.abc import Sequence

from videogen.agent.beat_plan import BeatPlan
from videogen.agent.creative_direction import CreativeDirectionAgent
from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec

_PLAN_JSON = """\
Here is my creative direction.

```json
{
  "beats": [
    {"id": "b1", "transcript_span": [0, 3], "role": "world-1", "intent": "set the pain",
     "asset_spec": {"kind": "broll-image", "brief": "cluttered desk"}},
    {"id": "b2", "transcript_span": [4, 9], "role": "climax", "intent": "the payoff",
     "asset_spec": {"kind": "broll-image", "brief": "parents building a robot"}}
  ]
}
```
"""


class _FixedClient:
    """Returns one canned assistant reply regardless of input."""

    model = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        return AssistantTurn(text=self._text)


def test_generate_returns_a_parsed_beat_plan() -> None:
    agent = CreativeDirectionAgent(_FixedClient(_PLAN_JSON))
    plan = agent.generate(brief="b", transcript="the desk is a mess and then we ship")

    assert isinstance(plan, BeatPlan)
    assert [b.id for b in plan.beats] == ["b1", "b2"]
    climax = next(b for b in plan.beats if b.id == "b2")
    assert climax.role == "climax"
    assert climax.transcript_span == (4, 9)
    assert climax.asset_spec.kind == "broll-image"


def test_generate_prose_still_returns_plain_text_for_the_legacy_fallback() -> None:
    agent = CreativeDirectionAgent(_FixedClient("1. Open on a stopwatch. 2. Cut to the workflow."))
    out = agent.generate_prose(brief="b", transcript="t")

    assert isinstance(out, str)
    assert "stopwatch" in out
