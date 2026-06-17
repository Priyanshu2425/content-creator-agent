"""Title overlay + add_title op (texthook/01): the static text-hook headline.

A new additive overlay type that places a static headline distinct from captions, compiling to the
existing IR TextLayer. Tests cover the Builder op, its param validation, and the IR compilation.
"""

from __future__ import annotations

from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Asset, AssetType, LayoutName, TitleOverlay
from videogen.kernel.ir import TextLayer
from videogen.kernel.validator import ErrorCode


def _builder() -> Builder:
    b = Builder.new(
        voiceover="host",
        duration=10.0,
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
    )
    b.add_scene(LayoutName.full, 0.0, 10.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    return b


def test_add_title_places_an_additive_title_overlay() -> None:
    b = _builder()
    result = b.add_title("Stop scrolling", 0.0, 2.5, placement="upper-third")

    assert result.ok
    overlays = b.composition.overlays
    assert len(overlays) == 1
    title = overlays[0]
    assert isinstance(title, TitleOverlay)
    assert title.text == "Stop scrolling"
    assert title.placement == "upper-third"


def test_add_title_rejects_empty_text() -> None:
    b = _builder()
    result = b.add_title("   ", 0.0, 2.5)

    assert not result.ok
    # rejected by the registry param validation (two-phase); the overlays list stays empty
    assert b.composition.overlays == []


def test_title_compiles_to_a_text_layer_with_title_style() -> None:
    b = _builder()
    b.add_title("Stop scrolling", 0.0, 2.5, placement="upper-third")
    ir = compile_ir(b.composition, fps=30, duration=10.0)

    titles = [layer for layer in ir.layers if isinstance(layer, TextLayer) and layer.style == "title"]
    assert len(titles) == 1
    title_layer = titles[0]
    assert title_layer.runs[0].text == "Stop scrolling"
    assert title_layer.start == 0.0 and title_layer.end == 2.5
    # upper-third placement lifts the headline via a vertical translate
    assert title_layer.transform is not None
    assert title_layer.transform.translate_y is not None


def test_center_placement_emits_no_vertical_translate() -> None:
    b = _builder()
    b.add_title("Centered hook", 0.0, 2.0, placement="center")
    ir = compile_ir(b.composition, fps=30, duration=10.0)

    title_layer = next(
        layer for layer in ir.layers if isinstance(layer, TextLayer) and layer.style == "title"
    )
    assert title_layer.transform is None


def test_title_is_distinct_from_the_captions_track() -> None:
    b = _builder()
    b.add_title("Hook", 0.0, 2.0)
    # a title is an overlay, not a caption -- the captions track stays empty
    assert b.composition.captions == []
    assert len(b.composition.overlays) == 1
