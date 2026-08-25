"""Deterministic placement: execute(beat_plan, assets, transcript) -> ops (ADR 0012).

execute() is the regression seam the prose-matching placement path lacked. These tests assert
*where* assets land given a typed BeatPlan and beat-keyed assets -- never how the function loops.
A fake BeatPlan + stub assets + a stubbed word-indexed transcript is all it needs; no Builder, no
model, no backend.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.beat_execute import execute
from videogen.agent.beat_plan import AssetSpec, Beat, BeatPlan
from videogen.agent.dispatch import NewAsset
from videogen.kernel.composition import Asset, AssetType


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


# words 0..3 span 0.0s -> 2.0s in half-second steps.
TRANSCRIPT = _Transcript(
    [
        _Word("the", 0.0, 0.5),
        _Word("payoff", 0.5, 1.0),
        _Word("arrives", 1.0, 1.5),
        _Word("now", 1.5, 2.0),
    ]
)


def _broll(beat_id: str) -> NewAsset:
    return NewAsset(
        asset_id=f"asset_{beat_id}",
        asset=Asset(type=AssetType.image, src=f"{beat_id}.png"),
        description="b-roll",
        beat_id=beat_id,
    )


def test_one_broll_beat_places_its_asset_on_the_span() -> None:
    """A single broll-image beat: add a scene over the span's seconds and fill it with the bound
    asset -- looked up by beat_id, never re-matched by description."""
    plan = BeatPlan(
        beats=(
            Beat(
                id="b1",
                transcript_span=(1, 2),  # words "payoff arrives" -> 0.5s..1.5s
                role="climax",
                intent="the payoff lands",
                asset_spec=AssetSpec(kind="broll-image", brief="parents building"),
            ),
        )
    )
    ops = execute(plan, {"b1": _broll("b1")}, TRANSCRIPT)

    add_scene = next(op for op in ops if op.name == "add_scene")
    fill = next(op for op in ops if op.name == "fill_region")

    assert add_scene.args["start"] == 0.5
    assert add_scene.args["end"] == 1.5
    assert fill.args["scene_id"] == add_scene.args["id"]
    assert fill.args["asset_id"] == "asset_b1"
