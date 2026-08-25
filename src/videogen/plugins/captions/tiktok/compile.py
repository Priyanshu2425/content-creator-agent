"""The ``tiktok`` caption renderer's pure compile (ADR 0010, ADR 0002).

Turns the renderer's typed params + the caption span into the IR pieces of its ``text`` layer. As
with ``highlight-box``, the animation is owned by the TS component (the line's enter spring and the
active-word highlight are driven there from each run's spoken window), so this style carries no
layer-level animation tracks: a flat opacity and no transform. ``emphasis`` is irrelevant to the
karaoke highlight look, so it is always ``False``.
"""

from __future__ import annotations

from videogen.kernel.ir import TikTokStyle, constant
from videogen.plugins.captions.registry import CompiledCaptionStyle
from videogen.plugins.captions.tiktok.params import TikTokParams


def compile_tiktok(params: TikTokParams, start: float, end: float) -> CompiledCaptionStyle:
    """Compile the tiktok params into IR visual props (no layer-level animation tracks)."""
    props = TikTokStyle(
        font_size=params.font_size,
        font_weight=params.font_weight,
        color=params.color,
        active_color=params.active_color,
        stroke_width=params.stroke_width,
        stroke_color=params.stroke_color,
        pop_seconds=params.pop_seconds,
        pop_start_scale=params.pop_start_scale,
        pop_translate_y=params.pop_translate_y,
    )
    return CompiledCaptionStyle(
        props=props, opacity=constant(1.0), transform=None, emphasis=False
    )
