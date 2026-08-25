"""The chain's deterministic prep step (ADR 0013): zip beats to assets + resolve spans to seconds.

This is the chain's anti-drift core. Two pure lookups, no model:

1. **zip** -- each beat is paired with the asset whose ``beat_id`` matches it. A beat with no matching
   asset becomes an explicit ``(beat, None)`` pair, so a failed generation is *visible* rather than
   silently absent.
2. **resolve** -- each beat's word-index ``transcript_span`` is turned into concrete ``[start_s,
   end_s]`` from the transcript's per-word timings, so the Composer never does timestamp arithmetic.

The output preserves the BeatPlan's order. Because it is pure, a fake BeatPlan + stub assets + a
word-timed transcript fully exercise it -- no Builder, no model, no backend (the regression seam the
LLM placement path lacks).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from videogen.agent.beat_plan import Beat, BeatPlan
from videogen.agent.dispatch import NewAsset
from videogen.kernel.builder import TranscriptLike


@dataclass(frozen=True)
class ResolvedBeat:
    """A beat with its span resolved to seconds and its bound asset attached (``None`` if missing).

    ``asset is None`` is the explicit "hole" the Composer fills by rule (punch-in / host-aroll /
    drop); a ``host-aroll`` beat is always ``None`` here because its asset is the existing host track,
    not a generated asset (ADR 0012)."""

    beat: Beat
    start_s: float
    end_s: float
    asset: NewAsset | None

    @property
    def is_hole(self) -> bool:
        """A non-host beat whose generated asset never arrived."""
        return self.asset is None and self.beat.asset_spec.kind != "host-aroll"


def prep(
    plan: BeatPlan,
    assets: Iterable[NewAsset] | Mapping[str, NewAsset],
    transcript: TranscriptLike,
) -> list[ResolvedBeat]:
    """Pair each beat with its beat-keyed asset and resolve its word-index span to seconds.

    ``assets`` may be a sequence of ``NewAsset`` (indexed here by ``beat_id``) or an already-built
    ``beat_id -> NewAsset`` mapping. Order follows the BeatPlan.
    """
    index = dict(assets) if isinstance(assets, Mapping) else _index_by_beat(assets)
    words = transcript.words
    n = len(words)
    if n == 0:
        raise ValueError("cannot resolve beat spans against an empty transcript")

    resolved: list[ResolvedBeat] = []
    for beat in plan.beats:
        start_s, end_s = _span_seconds(beat.transcript_span, words, n)
        resolved.append(
            ResolvedBeat(beat=beat, start_s=start_s, end_s=end_s, asset=index.get(beat.id))
        )
    return resolved


def _index_by_beat(assets: Iterable[NewAsset]) -> dict[str, NewAsset]:
    """Build a ``beat_id -> NewAsset`` index, dropping assets that carry no beat tag. Later wins."""
    out: dict[str, NewAsset] = {}
    for asset in assets:
        if asset.beat_id:
            out[asset.beat_id] = asset
    return out


def _span_seconds(span: tuple[int, int], words: object, n: int) -> tuple[float, float]:
    """Resolve an inclusive (start_word_idx, end_word_idx) span to (start_s, end_s), clamped in range.

    Indices are clamped to ``[0, n-1]`` and ordered low->high defensively, so an out-of-range or
    reversed span (a sloppy plan) resolves to a real on-timeline window rather than raising.
    """
    lo, hi = sorted((int(span[0]), int(span[1])))
    lo = max(0, min(lo, n - 1))
    hi = max(0, min(hi, n - 1))
    return words[lo].start, words[hi].end  # type: ignore[index]
