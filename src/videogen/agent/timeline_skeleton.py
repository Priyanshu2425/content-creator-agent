"""TimelineSkeleton: the Director's deterministic cross-layer change scaffold (restructure/04).

The former IdealCuts stage is dissolved into the Director (ADR 0008): the LLM cut-planning becomes
part of the Director's own authoring, and the deterministic part — merging the known change sources
into one sorted, de-duplicated list — lives here as a pure, unit-testable function.

The skeleton seeds the Director's sense of *when the frame already changes*: the reserved hook-window
start (the text hook lands on frame one), the caption-pop cadence (word starts), and any hard cuts
known up front. The Director consults it so it does not stack redundant motion and knows which
window to keep clear, then authors the actual cuts on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFAULT_HOOK_WINDOW = (0.0, 3.0)
_DEFAULT_MIN_CHANGE_INTERVAL = 1.5


@dataclass(frozen=True)
class TimelineSkeleton:
    """The merged change scaffold. ``change_list`` is the sorted, de-duplicated union of sources."""

    duration: float
    hook_window: tuple[float, float]
    caption_cadence: tuple[float, ...]
    hard_cuts: tuple[float, ...]
    change_list: tuple[float, ...]

    def summary(self) -> str:
        """A compact line for the Director's opening context (tokens, not prose)."""
        cadence = ", ".join(f"{t:.1f}" for t in self.change_list)
        return (
            f"Timeline skeleton -- hook window {self.hook_window[0]:.1f}-{self.hook_window[1]:.1f}s "
            f"(keep clear of competing overlays); known change beats at [{cadence}]s "
            f"({len(self.caption_cadence)} caption pops). Author cuts around these; "
            f"avoid stacking changes within {_DEFAULT_MIN_CHANGE_INTERVAL}s."
        )


def build_skeleton(
    *,
    transcript: Any,
    duration: float,
    hard_cuts: tuple[float, ...] = (),
    hook_window: tuple[float, float] = _DEFAULT_HOOK_WINDOW,
    min_change_interval: float = _DEFAULT_MIN_CHANGE_INTERVAL,
) -> TimelineSkeleton:
    """Merge the known change sources into one sorted, de-duplicated change list.

    Sources: the hook-window start (always present -- the text hook is on frame one), the caption
    cadence (transcript word starts), and any supplied ``hard_cuts``. Timestamps outside
    ``[0, duration]`` are dropped; neighbours closer than ``min_change_interval`` collapse to the
    earlier one so the scaffold never floods the Director with sub-threshold beats.
    """
    cadence = _word_starts(transcript)
    candidates = sorted(
        {
            round(float(t), 3)
            for t in (hook_window[0], *cadence, *hard_cuts)
            if 0.0 <= float(t) <= duration
        }
    )
    change_list = _dedupe(candidates, min_change_interval)
    return TimelineSkeleton(
        duration=duration,
        hook_window=hook_window,
        caption_cadence=tuple(cadence),
        hard_cuts=tuple(hard_cuts),
        change_list=change_list,
    )


def _word_starts(transcript: Any) -> tuple[float, ...]:
    words = getattr(transcript, "words", None) or ()
    return tuple(float(w.start) for w in words if getattr(w, "start", None) is not None)


def _dedupe(sorted_ts: list[float], min_gap: float) -> tuple[float, ...]:
    out: list[float] = []
    for t in sorted_ts:
        if not out or t - out[-1] >= min_gap:
            out.append(t)
    return tuple(out)
