"""Two-tier validator: local hard errors vs global reported warnings, and the submit gate.

These tests assert external behavior -- the error/warning *codes* and the gate predicate -- not
the validator's internals. The load-bearing case (CONTEXT.md coverage rules) is the tier split: a
gap warns but never blocks the submit gate, while any local error does (ADR 0004).
"""

from __future__ import annotations

from collections.abc import Iterable

from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Caption,
    CaptionStyle,
    Composition,
    InsertOverlay,
    LayoutName,
    Overlay,
    Ref,
    RegionName,
    Scene,
)
from videogen.kernel.validator import (
    ErrorCode,
    GlobalWarning,
    LocalError,
    WarningCode,
    can_submit_render,
    validate,
    validate_global,
    validate_local,
)

DURATION = 10.0

_DEFAULT_ASSETS = {
    "vo": Asset(type=AssetType.audio, src="vo.m4a"),
    "host": Asset(type=AssetType.video, src="host.mp4"),
    "broll": Asset(type=AssetType.image, src="tweet.png"),
}


def _comp(
    *,
    scenes: list[Scene] | None = None,
    captions: list[Caption] | None = None,
    overlays: list[Overlay] | None = None,
    assets: dict[str, Asset] | None = None,
    voiceover: str = "vo",
) -> Composition:
    return Composition(
        assets=_DEFAULT_ASSETS if assets is None else assets,
        voiceover=Audio(asset=voiceover),
        scenes=scenes or [],
        captions=captions or [],
        overlays=overlays or [],
    )


def _scene(
    sid: str,
    start: float,
    end: float,
    *,
    layout: LayoutName = LayoutName.full,
    regions: dict[RegionName, Ref] | None = None,
) -> Scene:
    if regions is None:
        regions = {RegionName.full: Ref(asset="host")}
    return Scene(id=sid, start=start, end=end, layout=layout, regions=regions)


def _codes(items: Iterable[LocalError | GlobalWarning]) -> set[ErrorCode | WarningCode]:
    return {item.code for item in items}


# --- the simplest video: one full-frame host scene ---


def test_full_host_scene_is_clean() -> None:
    comp = _comp(scenes=[_scene("s0", 0.0, DURATION)])
    result = validate(comp, duration=DURATION)
    assert result.ok
    assert result.errors == ()
    assert result.warnings == ()
    assert can_submit_render(comp, duration=DURATION)


def test_split_h_regions_are_valid() -> None:
    comp = _comp(
        scenes=[
            _scene(
                "s0",
                0.0,
                DURATION,
                layout=LayoutName.split_h,
                regions={
                    RegionName.top: Ref(asset="host"),
                    RegionName.bottom: Ref(asset="broll"),
                },
            )
        ]
    )
    assert validate_local(comp, duration=DURATION) == []


# --- local hard errors ---


def test_overlapping_scenes_are_a_hard_error() -> None:
    comp = _comp(scenes=[_scene("a", 0.0, 6.0), _scene("b", 5.0, 10.0)])
    errors = validate_local(comp, duration=DURATION)
    assert ErrorCode.SCENE_OVERLAP in _codes(errors)


def test_touching_scenes_do_not_overlap() -> None:
    # Half-open spans: a.end == b.start is a clean cut, not an overlap.
    comp = _comp(scenes=[_scene("a", 0.0, 5.0), _scene("b", 5.0, 10.0)])
    assert _codes(validate_local(comp, duration=DURATION)) == set()


def test_region_not_exposed_by_layout_is_an_error() -> None:
    # A `full` layout exposes only `full`; filling `top` is illegal.
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION, regions={RegionName.top: Ref(asset="host")})]
    )
    errors = validate_local(comp, duration=DURATION)
    assert ErrorCode.REGION_NOT_IN_LAYOUT in _codes(errors)
    assert any(e.entity_ref == "s0" for e in errors)


def test_dangling_scene_asset_reference_is_an_error() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION, regions={RegionName.full: Ref(asset="ghost")})]
    )
    assert ErrorCode.DANGLING_ASSET in _codes(validate_local(comp, duration=DURATION))


def test_dangling_voiceover_asset_is_an_error() -> None:
    comp = _comp(scenes=[_scene("s0", 0.0, DURATION)], voiceover="missing")
    errors = validate_local(comp, duration=DURATION)
    assert ErrorCode.DANGLING_ASSET in _codes(errors)
    assert any(e.entity_ref == "voiceover" for e in errors)


def test_caption_outside_voiceover_bounds_is_an_error() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        captions=[Caption(text="late", start=9.0, end=12.0, style=CaptionStyle.pill)],
    )
    assert ErrorCode.CAPTION_OUT_OF_BOUNDS in _codes(validate_local(comp, duration=DURATION))


def test_caption_start_after_end_is_an_error() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        captions=[Caption(text="bad", start=3.0, end=2.0, style=CaptionStyle.pill)],
    )
    assert ErrorCode.CAPTION_TIME_ORDER in _codes(validate_local(comp, duration=DURATION))


def test_scene_past_master_clock_is_an_error() -> None:
    comp = _comp(scenes=[_scene("s0", 0.0, 12.0)])
    assert ErrorCode.SCENE_OUT_OF_BOUNDS in _codes(validate_local(comp, duration=DURATION))


def test_overlay_target_region_not_exposed_is_an_error() -> None:
    # `insert` over `top`, but every scene is `full`, which never exposes `top`.
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        overlays=[InsertOverlay(start=1.0, end=2.0, target=RegionName.top, z=10)],
    )
    assert ErrorCode.TARGET_REGION_INVALID in _codes(validate_local(comp, duration=DURATION))


def test_overlay_target_region_exposed_by_active_scene_is_valid() -> None:
    comp = _comp(
        scenes=[
            _scene(
                "s0",
                0.0,
                DURATION,
                layout=LayoutName.split_h,
                regions={
                    RegionName.top: Ref(asset="host"),
                    RegionName.bottom: Ref(asset="broll"),
                },
            )
        ],
        overlays=[InsertOverlay(start=1.0, end=2.0, target=RegionName.top, z=10)],
    )
    assert _codes(validate_local(comp, duration=DURATION)) == set()


# --- global reported warnings (gaps) ---


def test_gap_between_scenes_warns_and_does_not_error() -> None:
    comp = _comp(scenes=[_scene("a", 0.0, 4.0), _scene("b", 6.0, 10.0)])
    assert validate_local(comp, duration=DURATION) == []
    warnings = validate_global(comp, duration=DURATION)
    assert WarningCode.SCENE_GAP in _codes(warnings)
    gap = next(w for w in warnings if w.code == WarningCode.SCENE_GAP)
    assert gap.span == (4.0, 6.0)


def test_trailing_gap_is_an_allowed_black_tail() -> None:
    comp = _comp(scenes=[_scene("s0", 0.0, 6.0)])
    assert validate_local(comp, duration=DURATION) == []
    warnings = validate_global(comp, duration=DURATION)
    assert WarningCode.TRAILING_GAP in _codes(warnings)
    assert next(w for w in warnings if w.code == WarningCode.TRAILING_GAP).span == (6.0, DURATION)


def test_leading_gap_warns() -> None:
    comp = _comp(scenes=[_scene("s0", 2.0, DURATION)])
    warnings = validate_global(comp, duration=DURATION)
    assert WarningCode.LEADING_GAP in _codes(warnings)


def test_no_scenes_warns() -> None:
    comp = _comp(scenes=[])
    warnings = validate_global(comp, duration=DURATION)
    assert WarningCode.NO_SCENES in _codes(warnings)


# --- the tier split: the load-bearing behavior of the phase ---


def test_gap_warning_does_not_block_submit_gate() -> None:
    comp = _comp(scenes=[_scene("a", 0.0, 4.0), _scene("b", 6.0, 10.0)])
    assert can_submit_render(comp, duration=DURATION)  # warned, but submittable


def test_local_error_blocks_submit_gate() -> None:
    comp = _comp(scenes=[_scene("a", 0.0, 6.0), _scene("b", 5.0, 10.0)])
    assert not can_submit_render(comp, duration=DURATION)


def test_local_and_global_tiers_are_independent() -> None:
    # A dangling asset (local error) alongside a trailing gap (global warning).
    comp = _comp(
        scenes=[_scene("s0", 0.0, 6.0, regions={RegionName.full: Ref(asset="ghost")})],
    )
    errors = validate_local(comp, duration=DURATION)
    warnings = validate_global(comp, duration=DURATION)
    assert _codes(errors) == {ErrorCode.DANGLING_ASSET}
    assert _codes(warnings) == {WarningCode.TRAILING_GAP}


def test_validate_composes_both_tiers() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, 6.0, regions={RegionName.full: Ref(asset="ghost")})],
    )
    result = validate(comp, duration=DURATION)
    assert not result.ok  # an error is present
    assert ErrorCode.DANGLING_ASSET in _codes(list(result.errors))
    assert WarningCode.TRAILING_GAP in _codes(list(result.warnings))
