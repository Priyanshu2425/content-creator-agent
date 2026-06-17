"""Karaoke captions: one line, per-word timing, active-word highlight (caption-generator change).

Captions are generated as lines carrying each word's spoken window; the compiler emits one timed
IR run per word and a highlight color, so the renderer can highlight the word being said now.
"""

from __future__ import annotations

from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Asset, AssetType, CaptionStyle, LayoutName
from videogen.kernel.ir import TextLayer
from videogen.services.media import Transcript, Word


def _builder_with_line() -> Builder:
    b = Builder.new(
        voiceover="host", duration=10.0, assets={"host": Asset(type=AssetType.video, src="h.mp4")}
    )
    b.add_scene(LayoutName.full, 0.0, 10.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    transcript = Transcript(
        words=[
            Word(text="this", start=0.2, end=0.4),
            Word(text="is", start=0.4, end=0.6),
            Word(text="the", start=0.6, end=0.8),
            Word(text="hook", start=0.8, end=1.2),
        ]
    )
    b.add_captions_from_transcript(transcript, style=CaptionStyle.pill)
    return b


def test_a_line_caption_compiles_to_one_text_layer_with_a_run_per_word() -> None:
    b = _builder_with_line()
    ir = compile_ir(b.composition, fps=30, duration=10.0)

    texts = [layer for layer in ir.layers if isinstance(layer, TextLayer)]
    assert len(texts) == 1  # one line, not four separate word layers
    layer = texts[0]
    assert [r.text for r in layer.runs] == ["this", "is", "the", "hook"]


def test_each_run_carries_its_own_spoken_window() -> None:
    b = _builder_with_line()
    ir = compile_ir(b.composition, fps=30, duration=10.0)
    layer = next(layer for layer in ir.layers if isinstance(layer, TextLayer))

    windows = [(r.start, r.end) for r in layer.runs]
    assert windows == [(0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.2)]


def test_caption_props_carry_a_highlight_color_for_the_active_word() -> None:
    b = _builder_with_line()
    ir = compile_ir(b.composition, fps=30, duration=10.0)
    layer = next(layer for layer in ir.layers if isinstance(layer, TextLayer))

    assert layer.props.highlight_color is not None


def test_line_layer_spans_the_first_to_last_word() -> None:
    b = _builder_with_line()
    ir = compile_ir(b.composition, fps=30, duration=10.0)
    layer = next(layer for layer in ir.layers if isinstance(layer, TextLayer))

    assert layer.start == 0.2 and layer.end == 1.2
