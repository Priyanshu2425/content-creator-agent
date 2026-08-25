"""TextHookToTAgent (ADR 0011): the Tree-of-Thoughts variant of the text-hook worker.

Like ``test_text_hook.py``, these script a fake ``ModelClient`` and assert the worker's *contract* --
it searches a payoff-frame -> phrasing tree and returns a valid ``HookProposal`` (ranked candidates
spanning >= 3 patterns, a recommended pick), degrades gracefully when output is unusable, and feeds
the transcript to the model. The stub routes by the system prompt so it is robust to how many calls
the search makes.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec
from videogen.agent.text_hook import HookProposal
from videogen.agent.text_hook_tot import TextHookToTAgent
from videogen.agent.tot.config import ToTConfig

_FRAMES = [
    '{"label":"literal","payoff":"a faster editing workflow","rationale":"r"}',
    '{"label":"emotional","payoff":"feel in control of your edits","rationale":"r"}',
    '{"label":"contrarian","payoff":"most editing advice is wrong","rationale":"r"}',
]
_HOOKS = [
    '{"text":"Stop editing like this","pattern":"contradiction","rationale":"r"}',
    '{"text":"The mistake costing you hours","pattern":"curiosity_gap","rationale":"r"}',
    '{"text":"Editors: do this instead","pattern":"audience_callout","rationale":"r"}',
    '{"text":"A faster way to cut","pattern":"complement","rationale":"r"}',
]


class RoutedClient:
    """Routes by system prompt: frame JSON for the strategist, hook JSON for HookSmith, a ranking for
    the editor. Cycles its pools so it answers any number of calls."""

    model = "fake"

    def __init__(self, *, frames=_FRAMES, hooks=_HOOKS, usable: bool = True) -> None:
        self._frames = itertools.cycle(frames)
        self._hooks = itertools.cycle(hooks)
        self._usable = usable
        self.seen: list[str] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.seen.append(history[-1].text if history else "")
        if not self._usable:
            return AssistantTurn(text="sorry, I cannot help with that")
        if "scoring a single" in system:  # value evaluator (hybrid frame gate)
            return AssistantTurn(text='{"score": 4}')
        if "interpretation of the video's" in system or "commit to ONE" in system:
            return AssistantTurn(text=next(self._frames))
        if "on-screen text hook" in system:
            return AssistantTurn(text=next(self._hooks))
        if "Rank" in system or "editor" in system:
            return AssistantTurn(text='{"ranking":[0,1,2]}')
        return AssistantTurn(text="")


def _agent(client: RoutedClient) -> TextHookToTAgent:
    # Same stub for hot + cold; it routes by system prompt. Small budget keeps the search bounded.
    cfg = ToTConfig(max_depth=2, n_generate_sample=3, breadth_limit=2, n_evaluate_sample=3)
    return TextHookToTAgent(hot_client=client, cold_client=client, config=cfg)


def test_returns_a_valid_hook_proposal_spanning_multiple_patterns() -> None:
    proposal = _agent(RoutedClient()).generate(
        transcript="we show a faster way to edit", goal="organic"
    )

    assert isinstance(proposal, HookProposal)
    assert len(proposal.candidates) >= 3
    assert len({c.pattern for c in proposal.candidates}) >= 3
    assert proposal.recommended == 1
    assert proposal.recommended_text().strip() != ""
    # ranks are a contiguous 1..n
    assert [c.rank for c in proposal.candidates] == list(range(1, len(proposal.candidates) + 1))


def test_degrades_gracefully_when_output_is_unusable() -> None:
    proposal = _agent(RoutedClient(usable=False)).generate(transcript="x", goal="organic")

    # No frame ever parsed -> the search yields no leaves -> legacy reinforce fallback, not a crash.
    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].pattern == "reinforce"
    assert proposal.recommended == 1


def test_transcript_reaches_the_model() -> None:
    client = RoutedClient()
    _agent(client).generate(transcript="unique-transcript-marker", goal="ad")

    assert any("unique-transcript-marker" in seen for seen in client.seen)
