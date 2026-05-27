"""Resolver: (composition, t) -> frame description, plus a whole-Composition textual timeline.

Frame state is *derived* by reading the declarative document at ``t`` (ADR 0001), never by replaying
operations, so resolution is total and order-independent. These tests assert the reported frame
state (owning scene, layout, region fills, active overlays/captions, paint order) and the timeline
text -- the agent's cheap, always-available perception channel (ADR 0004).
"""

from __future__ import annotations

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
    ZoomOverlay,
)
from videogen.kernel.resolver import resolve, timeline

DURATION = 10.0

_ASSETS = {
    "vo": Asset(type=AssetType.audio, src="vo.m4a"),
    "host": Asset(type=AssetType.video, src="host.mp4"),
    "broll": Asset(type=AssetType.image, src="tweet.png"),
}


def _comp(
    *,
    scenes: list[Scene] | None = None,
    captions: list[Caption] | None = None,
    overlays: list[Overlay] | None = None,
) -> Composition:
    return Composition(
        assets=_ASSETS,
        voiceover=Audio(asset="vo"),
        scenes=scenes or [],
        captions=captions or [],
        overlays=overlays or [],
    )


def _full_scene(sid: str, start: float, end: float, asset: str = "host") -> Scene:
    return Scene(
        id=sid,
        start=start,
        end=end,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset=asset)},
    )


# --- the frame description ---


def test_resolve_reports_owning_scene_layout_and_region_fills() -> None:
    comp = _comp(scenes=[_full_scene("s0", 0.0, DURATION)])
    frame = resolve(comp, 5.0)
    assert not frame.is_black
    assert frame.scene_id == "s0"
    assert frame.layout == LayoutName.full
    assert [(f.region, f.asset) for f in frame.regions] == [(RegionName.full, "host")]


def test_resolve_reports_split_h_region_fills() -> None:
    scene = Scene(
        id="s0",
        start=0.0,
        end=DURATION,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
    )
    frame = resolve(_comp(scenes=[scene]), 1.0)
    fills = {f.region: f.asset for f in frame.regions}
    assert fills == {RegionName.top: "host", RegionName.bottom: "broll"}


def test_resolve_in_a_gap_is_black_with_no_base_scene() -> None:
    comp = _comp(scenes=[_full_scene("a", 0.0, 4.0), _full_scene("b", 6.0, 10.0)])
    frame = resolve(comp, 5.0)
    assert frame.is_black
    assert frame.scene_id is None
    assert frame.layout is None
    assert frame.regions == ()


def test_scene_boundaries_are_half_open() -> None:
    # At t == 4.0 the second scene owns the frame, not the first (spans are [start, end)).
    comp = _comp(scenes=[_full_scene("a", 0.0, 4.0), _full_scene("b", 4.0, 8.0)])
    assert resolve(comp, 4.0).scene_id == "b"
    assert resolve(comp, 3.999).scene_id == "a"


# --- active overlays + captions + paint order ---


def test_active_captions_and_overlays_are_reported_in_paint_order() -> None:
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        captions=[
            Caption(text="low", start=0.0, end=2.0, style=CaptionStyle.pill, z=50),
            Caption(text="high", start=0.0, end=2.0, style=CaptionStyle.kinetic, z=100),
        ],
        overlays=[InsertOverlay(start=0.0, end=2.0, target=RegionName.full, z=10, asset="broll")],
    )
    frame = resolve(comp, 1.0)
    assert {c.text for c in frame.captions} == {"low", "high"}
    assert len(frame.overlays) == 1
    # Paint stack is bottom -> top by z: insert(10), pill caption(50), kinetic caption(100).
    assert [item.z for item in frame.paint_order] == [10, 50, 100]


def test_transform_overlay_is_active_but_not_painted() -> None:
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        overlays=[ZoomOverlay(start=0.0, end=2.0, target=RegionName.full, z=5)],
    )
    frame = resolve(comp, 1.0)
    assert len(frame.overlays) == 1
    assert frame.overlays[0].additive is False
    assert frame.paint_order == ()  # a transform overlay never enters the paint stack


def test_captions_composite_over_black_in_a_gap() -> None:
    comp = _comp(
        scenes=[_full_scene("a", 0.0, 4.0), _full_scene("b", 6.0, 10.0)],
        captions=[Caption(text="over black", start=4.0, end=6.0, style=CaptionStyle.pill)],
    )
    frame = resolve(comp, 5.0)
    assert frame.is_black
    assert [c.text for c in frame.captions] == ["over black"]


def test_inactive_overlays_and_captions_are_excluded() -> None:
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        captions=[Caption(text="early", start=0.0, end=1.0, style=CaptionStyle.pill)],
    )
    frame = resolve(comp, 5.0)
    assert frame.captions == ()


# --- order-independence (the document is declarative, ADR 0001) ---


def test_resolution_is_independent_of_scene_list_order() -> None:
    a = _full_scene("a", 0.0, 4.0)
    b = _full_scene("b", 4.0, 8.0)
    forward = _comp(scenes=[a, b])
    reversed_ = _comp(scenes=[b, a])
    assert resolve(forward, 2.0) == resolve(reversed_, 2.0)
    assert resolve(forward, 6.0) == resolve(reversed_, 6.0)


# --- the textual timeline ---


def test_timeline_covers_the_whole_composition_and_marks_gaps() -> None:
    comp = _comp(scenes=[_full_scene("a", 0.0, 4.0), _full_scene("b", 6.0, 10.0)])
    text = timeline(comp, duration=DURATION)
    assert "a" in text and "b" in text  # both scenes named
    assert "gap" in text.lower()  # the [4, 6] gap is shown as black


def test_timeline_lists_captions_with_text() -> None:
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        captions=[Caption(text="hello there", start=0.2, end=0.8, style=CaptionStyle.pill)],
    )
    text = timeline(comp, duration=DURATION)
    assert "hello there" in text


def test_timeline_marks_a_trailing_black_tail() -> None:
    comp = _comp(scenes=[_full_scene("s0", 0.0, 6.0)])
    text = timeline(comp, duration=DURATION)
    assert "gap" in text.lower()  # trailing [6, 10] black tail is shown


def test_timeline_lists_effect_overlays_with_their_target_region() -> None:
    # The agent reasons about an effect from the timeline without rendering (ADR 0004, story 12).
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        overlays=[ZoomOverlay(start=1.0, end=3.0, target=RegionName.full, z=5)],
    )
    text = timeline(comp, duration=DURATION)
    assert "zoom" in text  # the effect is named
    assert "full" in text  # against its target region
    assert "transform" in text  # classified as a transform (not painted)


def test_resolve_reports_an_active_effects_type_and_target() -> None:
    comp = _comp(
        scenes=[_full_scene("s0", 0.0, DURATION)],
        overlays=[ZoomOverlay(start=0.0, end=2.0, target=RegionName.full, z=5)],
    )
    active = resolve(comp, 1.0).overlays
    assert len(active) == 1
    assert active[0].type == "zoom" and active[0].target == RegionName.full
