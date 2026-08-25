"""Wrong-role back-fill guard: the chain's one hard placement rule (ADR 0012/0013, slice 07).

Pure predicate over an emitted Composition + the resolved beats. These tests lock the exact failure
ADR 0012 diagnosed: an asset generated for one role landing on a different-role span.
"""

from __future__ import annotations

from videogen.agent.beat_plan import AssetSpec, Beat
from videogen.agent.chain.prep import ResolvedBeat
from videogen.agent.chain.role_check import wrong_role_backfill_violations
from videogen.agent.dispatch import NewAsset
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Composition,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)


def _resolved(beat_id: str, role: str, start: float, end: float) -> ResolvedBeat:
    return ResolvedBeat(
        beat=Beat(id=beat_id, transcript_span=(0, 0), role=role, intent="x",
                  asset_spec=AssetSpec(kind="broll-image")),
        start_s=start,
        end_s=end,
        asset=NewAsset(
            asset_id=f"asset_{beat_id}",
            asset=Asset(type=AssetType.image, src=f"{beat_id}.png"),
            beat_id=beat_id,
        ),
    )


def _composition(scenes: list[Scene]) -> Composition:
    return Composition(
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
        voiceover=Audio(asset="host"),
        scenes=scenes,
    )


def _scene(scene_id: str, start: float, end: float, asset_id: str) -> Scene:
    return Scene(
        id=scene_id,
        start=start,
        end=end,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset=asset_id)},
    )


def test_same_role_placement_is_clean() -> None:
    climax = _resolved("b1", "climax", 0.5, 1.5)
    comp = _composition([_scene("s0", 0.5, 1.5, "asset_b1")])  # b1 lands on its own climax span
    assert wrong_role_backfill_violations(comp, [climax]) == []


def test_wrong_role_placement_is_flagged() -> None:
    climax = _resolved("b1", "climax", 0.5, 1.5)
    resolution = _resolved("b2", "resolution", 1.5, 2.5)
    # asset_b1 (made for climax) is placed on the resolution span -> the diagnosed bug.
    comp = _composition([_scene("s0", 1.5, 2.5, "asset_b1")])
    violations = wrong_role_backfill_violations(comp, [climax, resolution])

    assert len(violations) == 1
    v = violations[0]
    assert v.asset_id == "asset_b1"
    assert v.source_role == "climax"
    assert v.landed_role == "resolution"


def test_host_and_untracked_assets_are_not_subject_to_the_rule() -> None:
    climax = _resolved("b1", "climax", 0.5, 1.5)
    comp = _composition([_scene("s0", 0.5, 1.5, "host")])  # host asset has no source beat
    assert wrong_role_backfill_violations(comp, [climax]) == []


def test_multi_beat_correct_placement_is_clean() -> None:
    beats = [_resolved("b1", "climax", 0.5, 1.5), _resolved("b2", "resolution", 1.5, 2.5)]
    comp = _composition(
        [_scene("s0", 0.5, 1.5, "asset_b1"), _scene("s1", 1.5, 2.5, "asset_b2")]
    )
    assert wrong_role_backfill_violations(comp, beats) == []
