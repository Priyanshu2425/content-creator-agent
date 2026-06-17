"""Caption style presets: pill, word-bold, kinetic (Phase 3).

A **caption style** is a named preset controlling how a Caption looks. This module owns the only
place that knows what each of the three known styles means visually, and compiles a style into the
neutral IR vocabulary: a `TextStyle` of visual props plus, for `kinetic`, the pop-in animation
expressed as opacity and scale keyframe tracks. `compile_ir` calls `compile_caption_style` to build
each `text` Layer; the backend then paints the props and animates the tracks without ever knowing a
style by name (ADR 0002).

Captions are pinned to word timings on the voiceover master clock (ADR 0005), so the animation
keyframes are placed in absolute seconds relative to the caption's `start`.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.kernel.composition import CaptionStyle
from videogen.kernel.ir import Easing, Keyframe, TextStyle, Transform, Value, constant

# kinetic pop-in: opacity 0->1 and scale (small)->1 over this many seconds, eased to a settle.
KINETIC_POP_SECONDS = 0.18
KINETIC_START_SCALE = 0.6

# Static visual props per style. pill carries a dark rounded pill; word-bold and kinetic are plain
# text with no pill (background None). Sizes are px at the 1080-wide IR canvas.
_PROPS: dict[CaptionStyle, TextStyle] = {
    CaptionStyle.pill: TextStyle(
        font_size=64,
        font_weight=700,
        color="#FFFFFF",
        background="rgba(17,24,39,0.85)",  # dark rounded background for normal speech
        border_radius=24,
        padding_x=40,
        padding_y=18,
        highlight_color="#FFE14D",  # the word being spoken pops yellow on the dark pill
    ),
    CaptionStyle.word_bold: TextStyle(
        font_size=76,
        font_weight=800,
        color="#FFFFFF",  # plain white line; active word in accent
        highlight_color="#FFE14D",
    ),
    CaptionStyle.kinetic: TextStyle(
        font_size=120,
        font_weight=900,
        color="#FFFFFF",  # large line; active word pops accent
        highlight_color="#FFE14D",
    ),
}

# word-bold and kinetic both single out one key word; pill is normal narration.
_EMPHASIS: dict[CaptionStyle, bool] = {
    CaptionStyle.pill: False,
    CaptionStyle.word_bold: True,
    CaptionStyle.kinetic: True,
}


@dataclass(frozen=True)
class CompiledCaptionStyle:
    """The IR pieces a caption style contributes to its `text` Layer."""

    props: TextStyle
    opacity: Value
    transform: Transform | None
    emphasis: bool


def compile_caption_style(style: CaptionStyle, start: float, end: float) -> CompiledCaptionStyle:
    """Compile a caption style into IR visual props and (for kinetic) animation tracks.

    `pill` and `word-bold` are constant within their span: opacity is a flat 1.0 and there is no
    transform. `kinetic` pops in -- opacity rises 0->1 and scale springs from small to 1 over a
    short window from `start`, the system's first populated keyframe tracks. The pop window is
    clamped to half the caption's duration so the word is fully settled and visible by mid-span.
    """
    props = _PROPS[style]
    emphasis = _EMPHASIS[style]

    if style is not CaptionStyle.kinetic:
        return CompiledCaptionStyle(
            props=props, opacity=constant(1.0), transform=None, emphasis=emphasis
        )

    pop = min(KINETIC_POP_SECONDS, max(0.0, (end - start) * 0.5))
    settled = start + pop
    opacity = Value(
        keyframes=[
            Keyframe(t=start, value=0.0),
            Keyframe(t=settled, value=1.0, easing=Easing.ease_out),
        ]
    )
    scale = Value(
        keyframes=[
            Keyframe(t=start, value=KINETIC_START_SCALE),
            Keyframe(t=settled, value=1.0, easing=Easing.ease_out),
        ]
    )
    return CompiledCaptionStyle(
        props=props, opacity=opacity, transform=Transform(scale=scale), emphasis=emphasis
    )
