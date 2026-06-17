"""ClaudeReviewAgent: structural JSON review via Claude Code (review-agent switch).

The model is non-deterministic, so these target the contract: a scripted client's reply is parsed
into ReviewFeedback, the video arg is ignored (this reviewer reads the JSON), and unparseable or
clean replies degrade sensibly.
"""

from __future__ import annotations

from collections.abc import Sequence

from videogen.agent.claude_review import ClaudeReviewAgent
from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec
from videogen.agent.review import ReviewCategory, Severity
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, LayoutName


class FixedClient:
    def __init__(self, text: str) -> None:
        self._text = text
        self.seen: list[str] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.seen.append(history[-1].text if history else "")
        return AssistantTurn(text=self._text)


def _composition():
    b = Builder.new(
        voiceover="host", duration=10.0, assets={"host": Asset(type=AssetType.video, src="h.mp4")}
    )
    b.add_scene(LayoutName.full, 0.0, 10.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    return b.composition


_REPLY = """
Here is my review:
{
  "no_actionable_issues": false,
  "items": [
    {"at": 7.1, "until": 11.5, "category": "reel-fit", "severity": "blocking", "note": "scene cue one beat early"},
    {"at": 29.6, "category": "caption-sync", "severity": "blocking", "note": "uncaptioned tail"},
    {"at": 3.4, "category": "made-up-category", "severity": "weird", "note": "unknown enums coerce"}
  ]
}
"""


def test_parses_items_and_keys_them_to_the_timeline() -> None:
    client = FixedClient(_REPLY)
    fb = ClaudeReviewAgent(client=client).review(video=None, composition=_composition(), timeline="t")

    assert not fb.no_actionable_issues
    assert len(fb.items) == 3
    first = fb.items[0]
    assert first.at == 7.1 and first.until == 11.5
    assert first.category is ReviewCategory.reel_fit and first.severity is Severity.blocking


def test_unknown_category_and_severity_coerce_to_safe_defaults() -> None:
    fb = ClaudeReviewAgent(client=FixedClient(_REPLY)).review(
        video=None, composition=_composition(), timeline="t"
    )
    bad = fb.items[2]
    assert bad.category is ReviewCategory.reel_fit  # structural default
    assert bad.severity is Severity.suggestion


def test_the_composition_json_is_sent_to_the_model_not_the_video() -> None:
    client = FixedClient(_REPLY)
    ClaudeReviewAgent(client=client).review(
        video="/some/video.mp4", composition=_composition(), timeline="TL"
    )
    sent = client.seen[0]
    assert "Composition (JSON)" in sent and "s0" in sent  # the JSON, not a video reference


def test_unparseable_reply_is_treated_as_clean() -> None:
    fb = ClaudeReviewAgent(client=FixedClient("I couldn't produce JSON")).review(
        video=None, composition=_composition(), timeline="t"
    )
    assert fb.items == () and fb.no_actionable_issues
