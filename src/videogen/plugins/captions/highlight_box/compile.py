"""The ``highlight-box`` caption renderer's pure compile (ADR 0010, ADR 0002).

Turns the renderer's typed params + the caption span into the IR pieces of its ``text`` layer. The
per-word spring pop is owned by the TS component (driven by each run's spoken window), not the shared
opacity/scale sampler -- so unlike ``kinetic`` this style carries no layer animation tracks: the
layer opacity is a flat 1.0 and there is no transform. ``emphasis`` is irrelevant to a karaoke
highlighter look, so it is always ``False``.
"""

from __future__ import annotations

from videogen.kernel.ir import HighlightBoxStyle, constant
from videogen.plugins.captions.highlight_box.params import HighlightBoxParams
from videogen.plugins.captions.registry import CompiledCaptionStyle


def compile_highlight_box(
    params: HighlightBoxParams, start: float, end: float
) -> CompiledCaptionStyle:
    """Compile the highlight-box params into IR visual props (no layer-level animation tracks)."""
    props = HighlightBoxStyle(
        font_size=params.font_size,
        font_weight=params.font_weight,
        text_color=params.text_color,
        box_colors=list(params.box_colors),
        box_radius=params.box_radius,
        padding_x=params.padding_x,
        padding_y=params.padding_y,
        rotation_jitter_deg=params.rotation_jitter_deg,
        pop_seconds=params.pop_seconds,
        pop_start_scale=params.pop_start_scale,
    )
    return CompiledCaptionStyle(
        props=props, opacity=constant(1.0), transform=None, emphasis=False
    )
