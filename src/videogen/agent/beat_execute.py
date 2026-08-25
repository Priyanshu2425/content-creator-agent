"""Deterministic placement: turn a BeatPlan + beat-keyed assets into placement ops (ADR 0012).

This is the architectural payoff of ADR 0012. The Director used to re-interpret prose guidance and the
generated assets' text descriptions to *guess* which asset goes where; ``execute`` replaces the guess
with a binding. Each beat's ``transcript_span`` (word indices) resolves to a span in seconds via the
transcript the Director owns, and the asset tagged with that beat's id is placed there -- a lookup,
never a description re-match.

``execute`` is a pure function: given a plan, the beat-keyed assets available so far, and a transcript,
it returns op descriptors in the same vocabulary ``apply_op`` dispatches (``add_scene`` / ``fill_region``).
The loop applies them through the existing validated seam. Purity is the point -- a fake BeatPlan plus
stub assets can assert each asset lands on its beat's span/region with no Builder, model, or backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from videogen.agent.beat_plan import BeatPlan
from videogen.agent.dispatch import NewAsset
from videogen.kernel.builder import TranscriptLike

# Asset kinds that place a generated asset into a full-frame scene. host-aroll (no generated asset)
# and the hole rule for missing assets arrive in later slices.
_GENERATED_PLACEABLE = {"broll-image", "broll-video", "motion-graphic", "stat-viz"}


@dataclass(frozen=True)
class PlacementOp:
    """One placement op in ``apply_op``'s vocabulary -- the loop applies it through the validated seam."""

    name: str
    args: dict[str, Any]


def execute(
    plan: BeatPlan,
    assets: Mapping[str, NewAsset],
    transcript: TranscriptLike,
) -> list[PlacementOp]:
    """Place each beat's bound asset on its transcript span. Beats with no available asset are skipped
    here; the missing-asset hole rule is a later slice."""
    ops: list[PlacementOp] = []
    for beat in plan.beats:
        if beat.asset_spec.kind not in _GENERATED_PLACEABLE:
            continue
        asset = assets.get(beat.id)
        if asset is None:
            continue
        start, end = _span_seconds(beat.transcript_span, transcript)
        scene_id = f"beat-{beat.id}"
        ops.append(
            PlacementOp("add_scene", {"layout": "full", "start": start, "end": end, "id": scene_id})
        )
        ops.append(
            PlacementOp(
                "fill_region",
                {"scene_id": scene_id, "region": "full", "asset_id": asset.asset_id},
            )
        )
    return ops


def _span_seconds(span: tuple[int, int], transcript: TranscriptLike) -> tuple[float, float]:
    """Resolve an inclusive (start_word_idx, end_word_idx) span to (start_sec, end_sec)."""
    words = transcript.words
    start_idx, end_idx = span
    return words[start_idx].start, words[end_idx].end
