"""Review feedback contract: timestamped notes the video reviewer returns (Phase 8b, ADR 0004).

The video model is non-deterministic and external, so these tests pin the *shape* of its output and
the translation of that output into a revision brief the authoring agent can act on -- never the
prose of a real reviewer. ``ReviewFeedback`` carries timestamped, categorized, severity-tagged items
plus a ``no_actionable_issues`` flag that lets the finalization loop stop early; ``format_feedback``
turns those items into round-aware instructions (story 9, 15, 28, 29).
"""

from __future__ import annotations

from videogen.agent.review import (
    FeedbackItem,
    ReviewCategory,
    ReviewFeedback,
    Severity,
    format_feedback,
)


def test_feedback_carries_timestamped_categorized_severity_tagged_items() -> None:
    feedback = ReviewFeedback(
        items=(
            FeedbackItem(
                at=0.6,
                category=ReviewCategory.caption_sync,
                severity=Severity.blocking,
                note="'world' caption appears before it is spoken",
            ),
        ),
        no_actionable_issues=False,
    )

    item = feedback.items[0]
    assert item.at == 0.6
    assert item.until is None  # a point, not a span
    assert item.category is ReviewCategory.caption_sync
    assert item.severity is Severity.blocking


def test_categories_cover_the_full_motion_concerns() -> None:
    assert {c.value for c in ReviewCategory} == {
        "caption-sync",
        "caption-occlusion",
        "pacing",
        "framing",
        "audio",
        "reel-fit",
    }


def test_format_feedback_is_round_aware_and_lists_blocking_before_suggestions() -> None:
    feedback = ReviewFeedback(
        items=(
            FeedbackItem(
                at=1.0,
                until=2.0,
                category=ReviewCategory.pacing,
                severity=Severity.suggestion,
                note="the cut feels rushed",
            ),
            FeedbackItem(
                at=0.6,
                category=ReviewCategory.caption_sync,
                severity=Severity.blocking,
                note="caption drifts out of sync",
            ),
        ),
        no_actionable_issues=False,
    )

    brief = format_feedback(feedback, round_index=0, total_rounds=2)

    assert "round 1 of 2" in brief  # the agent knows which round it is answering (story 29)
    assert "caption-sync" in brief and "pacing" in brief  # each category surfaced
    assert "0.6s" in brief and "1-2s" in brief  # point and span timestamps rendered
    assert "caption drifts out of sync" in brief  # the note text travels through
    # blocking item is presented before the suggestion so edits can be prioritized (story 28)
    assert brief.index("caption-sync") < brief.index("pacing")
    assert "finish" in brief  # the agent is told to finish after applying edits


def test_review_system_prompt_names_the_reviewer_contract() -> None:
    from videogen.agent.prompts import REVIEW_SYSTEM_PROMPT

    for term in ("caption-sync", "caption-occlusion", "pacing", "framing"):
        assert term in REVIEW_SYSTEM_PROMPT
    assert "no_actionable_issues" in REVIEW_SYSTEM_PROMPT  # the early-stop signal
