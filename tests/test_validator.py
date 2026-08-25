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
    Composition,
    InsertOverlay,
    LayoutName,
    Overlay,
    Ref,
    RegionName,
    Scene,
    Transition,
    TransitionKind,
    ZoomOverlay,
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
    transitions: list[Transition] | None = None,
    assets: dict[str, Asset] | None = None,
    voiceover: str = "vo",
) -> Composition:
    return Composition(
        assets=_DEFAULT_ASSETS if assets is None else assets,
        voiceover=Audio(asset=voiceover),
        scenes=scenes or [],
        captions=captions or [],
        overlays=overlays or [],
        transitions=transitions or [],
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


# --- layout params: split-h ratio (validated by the registry contract, story 31) ---


def _split_scene(ratio: float) -> Scene:
    return Scene(
        id="s0",
        start=0.0,
        end=DURATION,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
        layout_params={"ratio": ratio},
    )


def test_split_h_ratio_out_of_range_is_a_hard_error() -> None:
    comp = _comp(scenes=[_split_scene(1.5)])
    assert ErrorCode.LAYOUT_PARAM_INVALID in _codes(validate_local(comp, duration=DURATION))


def test_split_h_in_range_ratio_is_clean() -> None:
    comp = _comp(scenes=[_split_scene(0.65)])
    assert validate_local(comp, duration=DURATION) == []


# --- transitions: sparse, keyed by afterScene (stories 18, 32) ---


def test_transition_after_a_known_scene_is_clean() -> None:
    comp = _comp(
        scenes=[_scene("a", 0.0, 5.0), _scene("b", 5.0, DURATION)],
        transitions=[Transition(after_scene="a", kind=TransitionKind.crossfade)],
    )
    assert validate_local(comp, duration=DURATION) == []


def test_transition_naming_an_unknown_scene_is_rejected() -> None:
    # A dangling afterScene must never reach the backend (story 32).
    comp = _comp(
        scenes=[_scene("a", 0.0, DURATION)],
        transitions=[Transition(after_scene="ghost", kind=TransitionKind.crossfade)],
    )
    errors = validate_local(comp, duration=DURATION)
    assert ErrorCode.DANGLING_TRANSITION in _codes(errors)
    assert any(e.entity_ref == "ghost" for e in errors)


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
    comp = _comp(scenes=[_scene("s0", 0.0, DURATION, regions={RegionName.top: Ref(asset="host")})])
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
        captions=[Caption(text="late", start=9.0, end=12.0, style="pill")],
    )
    assert ErrorCode.CAPTION_OUT_OF_BOUNDS in _codes(validate_local(comp, duration=DURATION))


def test_caption_start_after_end_is_an_error() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        captions=[Caption(text="bad", start=3.0, end=2.0, style="pill")],
    )
    assert ErrorCode.CAPTION_TIME_ORDER in _codes(validate_local(comp, duration=DURATION))


def test_scene_past_master_clock_is_an_error() -> None:
    comp = _comp(scenes=[_scene("s0", 0.0, 12.0)])
    assert ErrorCode.SCENE_OUT_OF_BOUNDS in _codes(validate_local(comp, duration=DURATION))


def test_overlay_target_region_not_exposed_is_an_error() -> None:
    # `insert` over `top`, but every scene is `full`, which never exposes `top`.
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        overlays=[InsertOverlay(start=1.0, end=2.0, target=RegionName.top, z=10, asset="broll")],
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
        overlays=[InsertOverlay(start=1.0, end=2.0, target=RegionName.top, z=10, asset="broll")],
    )
    assert _codes(validate_local(comp, duration=DURATION)) == set()


# --- effect overlays: full-span target validity + insert asset + params (Phase 6) ---


def _split(sid: str, start: float, end: float) -> Scene:
    return _scene(
        sid,
        start,
        end,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
    )


def test_transform_target_must_be_exposed_across_the_whole_span() -> None:
    # split-h [0,5] exposes `top`; the full scene [5,10] does not. A `top` zoom crossing the
    # boundary aims at a region that disappears mid-span -- now caught per-span (Phase 6).
    comp = _comp(
        scenes=[_split("hook", 0.0, 5.0), _scene("body", 5.0, 10.0)],
        overlays=[ZoomOverlay(start=4.0, end=6.0, target=RegionName.top)],
    )
    assert ErrorCode.TARGET_REGION_INVALID in _codes(validate_local(comp, duration=DURATION))


def test_transform_target_within_an_exposing_scene_is_valid() -> None:
    comp = _comp(
        scenes=[_split("hook", 0.0, DURATION)],
        overlays=[ZoomOverlay(start=2.0, end=4.0, target=RegionName.top)],
    )
    assert validate_local(comp, duration=DURATION) == []


def test_full_target_is_always_valid_even_over_a_gap() -> None:
    # `full` is always valid; a zoom may even span into a black gap (it reshapes nothing there).
    comp = _comp(
        scenes=[_scene("s0", 0.0, 4.0)],
        overlays=[ZoomOverlay(start=3.0, end=8.0, target=RegionName.full)],
    )
    assert ErrorCode.TARGET_REGION_INVALID not in _codes(validate_local(comp, duration=DURATION))


def test_insert_with_a_dangling_asset_is_an_error() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        overlays=[InsertOverlay(start=1.0, end=2.0, target=RegionName.full, asset="ghost")],
    )
    assert ErrorCode.DANGLING_ASSET in _codes(validate_local(comp, duration=DURATION))


def test_overlay_params_are_validated_through_the_registry() -> None:
    # A bad zoom scale is the type-specific (registry) half of two-phase validation (story 9).
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        overlays=[ZoomOverlay(start=1.0, end=2.0, target=RegionName.full, from_scale=-1.0)],
    )
    assert ErrorCode.OVERLAY_PARAM_INVALID in _codes(validate_local(comp, duration=DURATION))


def test_a_well_formed_effect_is_clean() -> None:
    comp = _comp(
        scenes=[_scene("s0", 0.0, DURATION)],
        overlays=[
            ZoomOverlay(start=1.0, end=5.0, target=RegionName.full, to_scale=1.3),
            InsertOverlay(start=2.0, end=4.0, target=RegionName.full, asset="broll", scale=0.3),
        ],
    )
    assert validate_local(comp, duration=DURATION) == []


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


# --- static-image hold-time: a still b-roll held >1s reads as dead (diagnose: bad placement) ---
# A non-blocking warning (authoring smell), surfaced to the Director for self-correction. A motion
# overlay (zoom/pan) over the region makes the image non-static, so it is exempt.


def _img(sid: str, start: float, end: float, *, asset: str = "broll") -> Scene:
    return _scene(sid, start, end, regions={RegionName.full: Ref(asset=asset)})


def test_static_image_held_over_one_second_warns() -> None:
    comp = _comp(scenes=[_img("s0", 0.0, 2.0)])  # "broll" is an image asset
    assert WarningCode.STATIC_IMAGE_TOO_LONG in _codes(validate_global(comp, duration=DURATION))


def test_static_image_within_one_second_does_not_warn() -> None:
    comp = _comp(scenes=[_img("s0", 0.0, 1.0)])  # exactly 1s is allowed (rule is ">1s")
    assert WarningCode.STATIC_IMAGE_TOO_LONG not in _codes(validate_global(comp, duration=DURATION))


def test_long_image_with_motion_overlay_does_not_warn() -> None:
    comp = _comp(
        scenes=[_img("s0", 0.0, 2.0)],
        overlays=[ZoomOverlay(target=RegionName.full, start=0.0, end=2.0)],
    )
    assert WarningCode.STATIC_IMAGE_TOO_LONG not in _codes(validate_global(comp, duration=DURATION))


def test_long_video_fill_does_not_warn() -> None:
    comp = _comp(scenes=[_img("s0", 0.0, 3.0, asset="host")])  # "host" is a video asset
    assert WarningCode.STATIC_IMAGE_TOO_LONG not in _codes(validate_global(comp, duration=DURATION))


def test_static_image_warning_never_blocks_the_gate() -> None:
    comp = _comp(scenes=[_img("s0", 0.0, 2.0)])
    assert can_submit_render(comp, duration=DURATION) is True
