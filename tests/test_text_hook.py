"""TextHookAgent (texthook/02): the text-hook worker the Director dispatches.

Single model turn: transcript + brand kit in, ranked hook candidates out. The model is
non-deterministic, so these tests script a fake ``ModelClient`` and assert the worker's contract --
it parses candidates, picks a recommended one, and degrades gracefully when the reply is unusable.
"""

from __future__ import annotations

from collections.abc import Sequence

from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec
from videogen.agent.text_hook import HookProposal, TextHookAgent


class FixedClient:
    """Returns a fixed assistant text every turn (the model's JSON reply)."""

    model = "fake"

    def __init__(self, text: str) -> None:
        self._text = text
        self.seen: list[str] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.seen.append(history[-1].text if history else "")
        return AssistantTurn(text=self._text)


_GOOD_REPLY = """
Here are the hooks:
{
  "candidates": [
    {"rank": 1, "text": "The mistake costing you hours", "pattern": "curiosity_gap", "rationale": "opens a loop"},
    {"rank": 2, "text": "Editors: stop doing this", "pattern": "audience_callout", "rationale": "names the viewer"},
    {"rank": 3, "text": "Faster edits in one step", "pattern": "complement", "rationale": "states the payoff"}
  ],
  "recommended": 1
}
"""


def test_parses_ranked_candidates_and_the_recommended_pick() -> None:
    agent = TextHookAgent(FixedClient(_GOOD_REPLY))
    proposal = agent.generate(transcript="we show a faster way to edit", goal="organic")

    assert isinstance(proposal, HookProposal)
    assert len(proposal.candidates) == 3
    assert proposal.recommended == 1
    assert proposal.recommended_text() == "The mistake costing you hours"
    # spans more than one pattern (not five variants of one idea)
    assert len({c.pattern for c in proposal.candidates}) >= 2


def test_degrades_gracefully_when_the_reply_is_unparseable() -> None:
    agent = TextHookAgent(FixedClient("sorry, I cannot help with that"))
    proposal = agent.generate(transcript="some transcript", goal="organic")

    # a single reinforce fallback rather than an invented payoff
    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].pattern == "reinforce"
    assert proposal.recommended == 1


def test_brand_kit_and_transcript_reach_the_model() -> None:
    client = FixedClient(_GOOD_REPLY)
    agent = TextHookAgent(client)
    agent.generate(
        transcript="unique-transcript-marker",
        goal="ad",
        audience="freelance editors",
        brand_kit={"caption_style": "kinetic"},
    )
    assert "unique-transcript-marker" in client.seen[0]


def test_proposal_to_text_lists_candidates_and_recommendation() -> None:
    agent = TextHookAgent(FixedClient(_GOOD_REPLY))
    proposal = agent.generate(transcript="x", goal="organic")
    text = proposal.to_text()

    assert "The mistake costing you hours" in text
    assert "recommended" in text.lower()
