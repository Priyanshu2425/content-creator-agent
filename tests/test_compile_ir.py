"""IR compilation: Compositions compile to the expected neutral IR (ADR 0002).

Snapshot tests in the style the plan prescribes (host-only -> captions -> layouts -> effects). The
host-only Composition produces the simplest IR -- one `media` and one `audio` Layer, no `text`,
constant tracks. The captioned Composition adds one `text` Layer per Caption: `pill`/`word-bold`
are constant within their span, while `kinetic` carries opacity and scale keyframe tracks driving
the pop-in -- the first populated animation in the system. Catching regressions here protects the
backend from bad IR before a render is ever attempted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Caption,
    CaptionStyle,
    Composition,
    CropRect,
    InsertOverlay,
    LayoutName,
    PanOverlay,
    Ref,
    RegionName,
    Scene,
    Transition,
    TransitionKind,
    ZoomOverlay,
)
from videogen.kernel.ir import MediaLayer, TextLayer

SNAPSHOT = Path(__file__).parent / "snapshots" / "host_only_ir.json"
CAPTIONS_SNAPSHOT = Path(__file__).parent / "snapshots" / "host_captions_ir.json"
REFERENCE_SNAPSHOT = Path(__file__).parent / "snapshots" / "reference_structure_ir.json"
EFFECTS_SNAPSHOT = Path(__file__).parent / "snapshots" / "effects_ir.json"

_ASSETS = {
    "vo": Asset(type=AssetType.audio, src="vo.m4a"),
    "host": Asset(type=AssetType.video, src="host.mp4"),
    "broll": Asset(type=AssetType.image, src="tweet.png"),
}


def _media(ir: object) -> list[MediaLayer]:
    return [layer for layer in ir.layers if isinstance(layer, MediaLayer)]  # type: ignore[attr-defined]


def _comp(*, scenes: list[Scene], transitions: list[Transition] | None = None) -> Composition:
    return Composition(
        assets=_ASSETS,
        voiceover=Audio(asset="vo"),
        scenes=scenes,
        transitions=transitions or [],
    )


def test_host_only_compiles_to_one_media_and_one_audio_layer(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinds = [layer.kind for layer in ir.layers]
    assert kinds.count("media") == 1
    assert kinds.count("audio") == 1
    assert "text" not in kinds  # captions are Phase 3


def test_host_only_media_layer_is_full_frame_for_the_whole_timeline(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    media = next(layer for layer in ir.layers if layer.kind == "media")
    assert media.start == 0.0
    assert media.end == 2.0
    assert media.transform is None  # no keyframes this phase; sampler runs its constant path


def test_voiceover_sets_ir_duration_and_audio_span(
    host_only_composition: Callable[..., Composition],
) -> None:
    # The voiceover is the master clock (ADR 0005): it defines the composition's duration.
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    audio = next(layer for layer in ir.layers if layer.kind == "audio")
    assert ir.duration == 2.0
    assert (audio.start, audio.end) == (0.0, 2.0)


def test_host_only_matches_ir_snapshot(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(SNAPSHOT.read_text())
    assert produced == expected


# --- captions (Phase 3) ---


def test_each_caption_compiles_to_a_text_layer_above_the_media(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinds = [layer.kind for layer in ir.layers]
    assert kinds.count("media") == 1
    assert kinds.count("audio") == 1
    assert kinds.count("text") == len(comp.captions)  # one text Layer per Caption

    media = next(layer for layer in ir.layers if layer.kind == "media")
    texts = [layer for layer in ir.layers if layer.kind == "text"]
    # Captions are additive and must paint above the host media (ADR 0001 z convention).
    assert all(layer.z > media.z for layer in texts)


def test_pill_and_word_bold_text_layers_are_constant_within_their_span(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    for layer in ir.layers:
        if layer.kind == "text" and layer.style in ("pill", "word-bold"):
            assert layer.transform is None  # no animation tracks
            assert len(layer.opacity.keyframes) == 1  # constant opacity


def test_kinetic_text_layer_carries_opacity_and_scale_keyframes(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinetic = next(
        layer for layer in ir.layers if layer.kind == "text" and layer.style == "kinetic"
    )
    caption = next(c for c in comp.captions if c.style.value == "kinetic")

    # Opacity rises 0 -> 1 over a short pop window from the caption start.
    opacity = kinetic.opacity.keyframes
    assert len(opacity) == 2
    assert opacity[0].t == caption.start and opacity[0].value == 0.0
    assert opacity[1].value == 1.0 and caption.start < opacity[1].t <= caption.end

    # Scale springs from small to a settled 1.0 over the same window.
    assert kinetic.transform is not None and kinetic.transform.scale is not None
    scale = kinetic.transform.scale.keyframes
    assert len(scale) == 2
    assert scale[0].t == caption.start and 0.0 < scale[0].value < 1.0
    assert scale[1].value == 1.0 and scale[1].t == opacity[1].t


def test_captions_match_ir_snapshot(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(CAPTIONS_SNAPSHOT.read_text())
    assert produced == expected


# --- layouts via the registry (Phase 5) ---


def test_split_h_compiles_to_two_media_layers_with_preset_geometry() -> None:
    scene = Scene(
        id="s0",
        start=0.0,
        end=4.0,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
    )
    ir = compile_ir(_comp(scenes=[scene]), fps=30, duration=4.0)

    media = _media(ir)
    assert len(media) == 2
    top = next(m for m in media if m.src == "host.mp4")
    bottom = next(m for m in media if m.src == "tweet.png")
    assert top.rect is not None and (top.rect.y, top.rect.height) == (0.0, 0.5)
    assert bottom.rect is not None and (bottom.rect.y, bottom.rect.height) == (0.5, 0.5)


def test_split_h_custom_ratio_reaches_the_ir_geometry() -> None:
    scene = Scene(
        id="s0",
        start=0.0,
        end=4.0,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
        layout_params={"ratio": 0.7},
    )
    ir = compile_ir(_comp(scenes=[scene]), fps=30, duration=4.0)
    top = next(m for m in _media(ir) if m.src == "host.mp4")
    assert top.rect is not None and top.rect.height == 0.7


def test_full_frame_broll_scene_compiles_to_a_media_layer_on_a_hard_cut() -> None:
    # Full-frame b-roll is an ordinary `full` Scene filled with a b-roll Asset (CONTEXT.md). It
    # enters/leaves on a hard cut: no transition authored, so constant opacity, full frame.
    host = Scene(
        id="host",
        start=0.0,
        end=3.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host")},
    )
    broll = Scene(
        id="broll",
        start=3.0,
        end=5.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="broll")},
    )
    ir = compile_ir(_comp(scenes=[host, broll]), fps=30, duration=5.0)

    broll_layer = next(m for m in _media(ir) if m.src == "tweet.png")
    assert broll_layer.rect is None  # full frame
    assert (broll_layer.start, broll_layer.end) == (3.0, 5.0)  # the b-roll's exact span
    assert len(broll_layer.opacity.keyframes) == 1  # hard cut: no cross-blend


def test_multi_scene_threads_one_continuous_voiceover() -> None:
    # The voiceover is the master clock: one audio layer spans the whole timeline through the cuts.
    scenes = [
        Scene(
            id="a",
            start=0.0,
            end=3.0,
            layout=LayoutName.full,
            regions={RegionName.full: Ref(asset="host")},
        ),
        Scene(
            id="b",
            start=3.0,
            end=6.0,
            layout=LayoutName.full,
            regions={RegionName.full: Ref(asset="broll")},
        ),
    ]
    ir = compile_ir(_comp(scenes=scenes), fps=30, duration=6.0)
    audio = [layer for layer in ir.layers if layer.kind == "audio"]
    assert len(audio) == 1
    assert (audio[0].start, audio[0].end) == (0.0, 6.0)


# --- transitions: sparse, keyed by afterScene (Phase 5) ---


def _two_full_scenes() -> list[Scene]:
    return [
        Scene(
            id="a",
            start=0.0,
            end=3.0,
            layout=LayoutName.full,
            regions={RegionName.full: Ref(asset="host")},
        ),
        Scene(
            id="b",
            start=3.0,
            end=6.0,
            layout=LayoutName.full,
            regions={RegionName.full: Ref(asset="broll")},
        ),
    ]


def test_absent_transition_is_a_cut_with_no_crossfade() -> None:
    ir = compile_ir(_comp(scenes=_two_full_scenes()), fps=30, duration=6.0)
    # Every media layer is constant-opacity: a cut paints nothing extra (sparse array, story 16).
    assert all(len(m.opacity.keyframes) == 1 for m in _media(ir))


def test_crossfade_emits_an_opacity_cross_blend_at_the_named_boundary() -> None:
    d = 0.5
    comp = _comp(
        scenes=_two_full_scenes(),
        transitions=[Transition(after_scene="a", kind=TransitionKind.crossfade, duration=d)],
    )
    ir = compile_ir(comp, fps=30, duration=6.0)
    boundary = 3.0

    outgoing = next(m for m in _media(ir) if m.src == "host.mp4")  # scene a
    incoming = next(m for m in _media(ir) if m.src == "tweet.png")  # scene b

    # Outgoing fades 1 -> 0 across the boundary window and is held on screen to blend under the cut.
    out_kfs = outgoing.opacity.keyframes
    assert (out_kfs[0].t, out_kfs[0].value) == (boundary, 1.0)
    assert (out_kfs[-1].t, out_kfs[-1].value) == (boundary + d, 0.0)
    assert outgoing.end == boundary + d  # extended past its scene to overlap the incoming

    # Incoming fades 0 -> 1 across the same window.
    in_kfs = incoming.opacity.keyframes
    assert (in_kfs[0].t, in_kfs[0].value) == (boundary, 0.0)
    assert (in_kfs[-1].t, in_kfs[-1].value) == (boundary + d, 1.0)


def test_crossfade_keys_off_scene_id_not_list_position() -> None:
    # Reordering the scenes list must not move the crossfade: it keys off the stable id (ADR 0001).
    scenes = _two_full_scenes()
    transitions = [Transition(after_scene="a", kind=TransitionKind.crossfade, duration=0.5)]
    forward = compile_ir(_comp(scenes=scenes, transitions=transitions), fps=30, duration=6.0)
    reversed_ = compile_ir(
        _comp(scenes=[scenes[1], scenes[0]], transitions=transitions), fps=30, duration=6.0
    )

    def blend(ir: object) -> tuple[float, int, int]:
        out = next(m for m in _media(ir) if m.src == "host.mp4")
        inc = next(m for m in _media(ir) if m.src == "tweet.png")
        return (out.end, len(out.opacity.keyframes), len(inc.opacity.keyframes))

    assert blend(forward) == blend(reversed_)
    # And it is a real crossfade, not a no-op, in both orderings.
    assert blend(forward) == (3.5, 2, 2)


# --- the reference-video structure, end to end, authored through the Builder (stories 28, 29) ---

REFERENCE_DURATION = 6.0


def _reference_composition() -> Composition:
    """A split-h hook cutting to a full host Scene and then to a full b-roll Scene, with a crossfade
    at the host->b-roll boundary. Authored through Phase 4 Builder operations, not hand-written JSON
    (the PRD's testing decision), so the fixture exercises the real authoring path."""
    b = Builder.new(voiceover="vo", duration=REFERENCE_DURATION, assets=_ASSETS)
    b.add_scene(LayoutName.split_h, 0.0, 2.0, id="hook", layout_params={"ratio": 0.6})
    b.fill_region("hook", RegionName.top, "host")
    b.fill_region("hook", RegionName.bottom, "broll")
    b.add_scene(LayoutName.full, 2.0, 4.0, id="host")
    b.fill_region("host", RegionName.full, "host", in_point=10.0)  # jump-cut into the one recording
    b.add_scene(LayoutName.full, 4.0, REFERENCE_DURATION, id="broll")
    b.fill_region("broll", RegionName.full, "broll")
    b.add_transition("host", TransitionKind.crossfade, duration=0.5)
    assert b.can_submit_render()  # the whole reference structure is gate-clean
    return b.composition


def test_reference_structure_matches_ir_snapshot() -> None:
    ir = compile_ir(_reference_composition(), fps=30, duration=REFERENCE_DURATION)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(REFERENCE_SNAPSHOT.read_text())
    assert produced == expected


# --- effects: zoom / pan / insert overlays (Phase 6) ---


def _full_host(end: float = 4.0) -> Scene:
    return Scene(
        id="s0",
        start=0.0,
        end=end,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host")},
    )


def _split_hook(end: float = 4.0, *, ratio: float = 0.5) -> Scene:
    return Scene(
        id="s0",
        start=0.0,
        end=end,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
        layout_params={"ratio": ratio},
    )


def _overlay_comp(scene: Scene, overlays: list, captions: list | None = None) -> Composition:  # type: ignore[type-arg]
    return Composition(
        assets=_ASSETS,
        voiceover=Audio(asset="vo"),
        scenes=[scene],
        overlays=overlays,
        captions=captions or [],
    )


def test_zoom_merges_a_scale_transform_onto_the_full_frame_base_layer() -> None:
    comp = _overlay_comp(
        _full_host(),
        [ZoomOverlay(start=1.0, end=3.0, target=RegionName.full, from_scale=1.0, to_scale=1.4)],
    )
    ir = compile_ir(comp, fps=30, duration=4.0)

    media = _media(ir)
    assert len(media) == 1  # a transform overlay adds NO new layer (CONTEXT.md)
    host = media[0]
    assert host.transform is not None and host.transform.scale is not None
    assert host.transform.scale.keyframes[-1].value == 1.4


def test_transform_overlay_does_not_scale_the_captions_above_it() -> None:
    comp = _overlay_comp(
        _full_host(),
        [ZoomOverlay(start=0.0, end=4.0, target=RegionName.full, to_scale=1.5)],
        captions=[Caption(text="hi", start=1.0, end=2.0, style=CaptionStyle.pill)],
    )
    ir = compile_ir(comp, fps=30, duration=4.0)

    text = next(layer for layer in ir.layers if isinstance(layer, TextLayer))
    # The pill caption is constant; the zoom under it must not introduce a scale track on the text.
    assert text.transform is None


def test_zoom_on_top_region_leaves_the_bottom_untouched() -> None:
    comp = _overlay_comp(
        _split_hook(),
        [ZoomOverlay(start=0.0, end=4.0, target=RegionName.top, to_scale=1.3)],
    )
    ir = compile_ir(comp, fps=30, duration=4.0)

    top = next(m for m in _media(ir) if m.src == "host.mp4")
    bottom = next(m for m in _media(ir) if m.src == "tweet.png")
    assert top.transform is not None and top.transform.scale is not None
    assert bottom.transform is None  # the bottom region is not reshaped (story 5)


def test_pan_merges_a_pixel_translate_onto_the_base_layer() -> None:
    comp = _overlay_comp(
        _full_host(),
        [PanOverlay(start=0.0, end=4.0, target=RegionName.full, dx=0.1, dy=0.0)],
    )
    ir = compile_ir(comp, fps=30, duration=4.0)  # default 1080-wide canvas

    host = _media(ir)[0]
    assert host.transform is not None and host.transform.translate_x is not None
    assert host.transform.translate_x.keyframes[-1].value == 0.1 * 1080


def test_insert_adds_one_painted_layer_ordered_by_z_against_captions() -> None:
    comp = _overlay_comp(
        _full_host(),
        [InsertOverlay(start=1.0, end=3.0, target=RegionName.full, z=50, asset="broll")],
        captions=[Caption(text="hi", start=1.0, end=2.0, style=CaptionStyle.pill)],  # z=100
    )
    ir = compile_ir(comp, fps=30, duration=4.0)

    media = _media(ir)
    assert len(media) == 2  # host + the floating insert
    host = next(m for m in media if m.src == "host.mp4")
    insert = next(m for m in media if m.src == "tweet.png")
    text = next(layer for layer in ir.layers if isinstance(layer, TextLayer))
    # One z space across inserts and captions: host(0) < insert(50) < caption(100).
    assert host.z == 0 and insert.z == 50 and text.z == 100


def test_a_zoom_z_is_inert_and_pulls_no_layer_into_the_paint_stack() -> None:
    # A transform overlay carries z structurally, but it must paint nothing and reorder nothing.
    comp = _overlay_comp(
        _full_host(),
        [ZoomOverlay(start=0.0, end=4.0, target=RegionName.full, z=999, to_scale=1.2)],
    )
    ir = compile_ir(comp, fps=30, duration=4.0)

    media = _media(ir)
    assert len(media) == 1  # no painted layer despite the high z
    assert media[0].z == 0  # the zoom's z did not transfer onto the base layer


def _effects_composition() -> Composition:
    """A full host Scene carrying a slow zoom, a floating insert, and a caption -- both effect kinds
    over a continuing scene with text on top, so the snapshot pins the transform/additive split."""
    return Composition(
        assets=_ASSETS,
        voiceover=Audio(asset="vo"),
        scenes=[_full_host()],
        overlays=[
            ZoomOverlay(start=0.0, end=4.0, target=RegionName.full, from_scale=1.0, to_scale=1.2),
            InsertOverlay(
                start=1.0, end=3.0, target=RegionName.full, z=50, asset="broll", fade=0.4
            ),
        ],
        captions=[Caption(text="watch this", start=0.5, end=2.0, style=CaptionStyle.pill)],
    )


def test_effects_match_ir_snapshot() -> None:
    ir = compile_ir(_effects_composition(), fps=30, duration=4.0)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(EFFECTS_SNAPSHOT.read_text())
    assert produced == expected


def test_region_crop_flows_into_the_media_layer() -> None:
    # A source crop set on a region fill (set_crop) compiles onto that region's media layer as a
    # normalized IR Rect; a fill with no crop stays None (the default centered cover).
    builder = Builder.new(
        voiceover="host", duration=2.0, assets={"host": Asset(type=AssetType.video, src="host.mp4")}
    )
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    builder.set_crop("s0", RegionName.full, CropRect(x=0.1, y=0.0, width=0.8, height=1.0))

    ir = compile_ir(builder.composition, fps=30, duration=2.0)
    media = next(layer for layer in ir.layers if isinstance(layer, MediaLayer))

    assert media.crop is not None
    assert (media.crop.x, media.crop.y, media.crop.width, media.crop.height) == (0.1, 0.0, 0.8, 1.0)
