"""ReviewAgent seam + full-motion feedback contract (Phase 8b, ADR 0004).

Phase 8's in-loop vision is image-based -- a still at ``t`` and a scene-preview strip -- which is
cheap but blind to motion. Whether captions stay synced across their whole span, whether a zoom
reads as smooth motion, whether a caption is occluded only while the host moves: these are
full-motion judgements a still cannot make. ADR 0004 reserved them for a separate, video-capable
review sub-agent. This module is that seam:

- ``ReviewAgent`` (Protocol) is the swap boundary -- the finalization loop depends on this
  interface, not a concrete video model (Gemini today, anything tomorrow). A concrete video adapter
  is Phase 9 wiring, as the authoring ``ModelClient`` adapter was deferred in Phase 8.
- ``ReviewFeedback`` is what the reviewer returns: timestamped, categorized, severity-tagged items
  plus ``no_actionable_issues`` so the loop can stop early rather than burn a render round.
- ``format_feedback`` translates that into a round-aware revision brief the Phase 8 authoring agent
  acts on -- corrections flow back through its existing validated op loop, not a new mutation path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from videogen.kernel.composition import Composition


class ReviewCategory(StrEnum):
    """The full-motion concerns a reviewer reports -- the problems a still cannot reveal."""

    caption_sync = "caption-sync"
    caption_occlusion = "caption-occlusion"
    pacing = "pacing"
    framing = "framing"
    audio = "audio"
    reel_fit = "reel-fit"


class Severity(StrEnum):
    """Whether a note must be fixed or is merely advisory; lets the loop prioritize edits."""

    blocking = "blocking"
    suggestion = "suggestion"


@dataclass(frozen=True)
class FeedbackItem:
    """One timeline-anchored observation. ``until`` is set for a span; ``None`` means a point."""

    at: float
    category: ReviewCategory
    severity: Severity
    note: str
    until: float | None = None


@dataclass(frozen=True)
class ReviewFeedback:
    """A review pass: the items observed, and whether nothing actionable remains (early stop)."""

    items: tuple[FeedbackItem, ...]
    no_actionable_issues: bool


class ReviewAgent(Protocol):
    """A video-capable reviewer that watches the full mp4 and returns timestamped feedback.

    The finalization loop depends only on this interface and the rendered artifact, so the concrete
    video model can be swapped without touching the gate (story 14, 20). The Composition and the
    Resolver timeline are passed as context so the reviewer can key its notes to timeline seconds.
    """

    def review(self, *, video: Path, composition: Composition, timeline: str) -> ReviewFeedback:
        """Watch ``video`` in full and return timestamped feedback keyed to the timeline."""
        ...


def _when(item: FeedbackItem) -> str:
    if item.until is None:
        return f"{item.at:g}s"
    return f"{item.at:g}-{item.until:g}s"


def _render_item(item: FeedbackItem) -> str:
    mark = "BLOCKING" if item.severity is Severity.blocking else "suggestion"
    return f"[{mark}] {item.category.value} @ {_when(item)}: {item.note}"


def format_feedback(feedback: ReviewFeedback, *, round_index: int, total_rounds: int) -> str:
    """Turn a review pass into a round-aware revision brief for the authoring agent.

    Blocking notes are listed before suggestions so the agent spends its op budget on what matters
    (story 28); the round number tells it which pass it is answering so it does not re-litigate
    notes it has already addressed (story 29). The agent applies corrections through its validated
    Builder-op loop and then calls ``finish``.
    """
    header = (
        f"Review round {round_index + 1} of {total_rounds}. A video-capable reviewer watched the "
        f"full rendered video and returned these timestamped notes. Apply corrective Builder ops "
        f"for the blocking items (suggestions are optional), keep the Composition passing the "
        f"submit-render gate, then call finish. Do not re-open notes you have already addressed."
    )
    ordered = sorted(feedback.items, key=lambda i: i.severity is not Severity.blocking)
    body = "\n".join(_render_item(item) for item in ordered)
    return f"{header}\n\n{body}"
