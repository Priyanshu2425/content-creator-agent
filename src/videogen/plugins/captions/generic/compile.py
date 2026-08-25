"""The ``generic`` caption renderer's pure compile (ADR 0010, ADR 0002).

Turns the renderer's typed params + the caption span into the IR pieces of its ``text`` layer: the
visual ``TextStyle`` props the backend paints, plus -- when ``pop_seconds`` is positive -- the
opacity and scale keyframe tracks that animate the pop-in. The pop rides the layer's
``opacity``/``transform.scale`` tracks evaluated by the shared keyframe sampler, so the animation is
data, not per-style component code (the kinetic look is just this renderer with a positive pop).

This is the exact behavior of the former ``compile_caption_style``: ``pill``/``word-bold`` (pop 0)
are constant within their span (opacity flat 1.0, no transform); ``kinetic`` (positive pop) springs
in over a window clamped to half the caption's duration so the word is settled by mid-span. Captions
are pinned to word timings on the voiceover master clock (ADR 0005), so the keyframes are placed in
absolute seconds relative to the caption's ``start``.
"""

from __future__ import annotations

from videogen.kernel.ir import Easing, Keyframe, TextStyle, Transform, Value, constant
from videogen.plugins.captions.generic.params import GenericCaptionParams
from videogen.plugins.captions.registry import CompiledCaptionStyle


def compile_generic(
    params: GenericCaptionParams, start: float, end: float
) -> CompiledCaptionStyle:
    """Compile the generic caption params into IR visual props and (for a pop) animation tracks."""
    props = TextStyle(
        font_size=params.font_size,
        font_weight=params.font_weight,
        color=params.color,
        background=params.background,
        border_radius=params.border_radius,
        padding_x=params.padding_x,
        padding_y=params.padding_y,
        highlight_color=params.highlight_color,
    )

    if params.pop_seconds <= 0.0:
        return CompiledCaptionStyle(
            props=props, opacity=constant(1.0), transform=None, emphasis=params.emphasis
        )

    # Pop-in: opacity 0->1 and scale (small)->1 over a window clamped to half the span, so the word
    # is fully settled and visible by mid-span (the former kinetic behavior, exactly).
    pop = min(params.pop_seconds, max(0.0, (end - start) * 0.5))
    settled = start + pop
    opacity = Value(
        keyframes=[
            Keyframe(t=start, value=0.0),
            Keyframe(t=settled, value=1.0, easing=Easing.ease_out),
        ]
    )
    scale = Value(
        keyframes=[
            Keyframe(t=start, value=params.pop_start_scale),
            Keyframe(t=settled, value=1.0, easing=Easing.ease_out),
        ]
    )
    return CompiledCaptionStyle(
        props=props, opacity=opacity, transform=Transform(scale=scale), emphasis=params.emphasis
    )
