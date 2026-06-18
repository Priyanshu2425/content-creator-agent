"""`title` additive overlay -- pure `to_ir` (texthook/01, ADR 0002).

The text hook: a static headline painted over the opening, distinct from captions. Emits exactly one
painted `text` layer (reusing the IR `TextLayer` the captions track already uses), styled large and
bold. ``placement`` maps to a vertical translate so the headline sits in the upper third rather than
on the caption band; ``center`` leaves it centred. No transform of base content -- a title is
additive.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, TitleOverlay
from videogen.kernel.ir import TextLayer, TextRun, TextStyle
from videogen.kernel.registry import CompileContext, OverlayFragment


def to_ir(overlay: Overlay, ctx: CompileContext) -> OverlayFragment:
    """Compile a title into one painted text layer -- a large, bold, static headline.

    Positioning (upper-third vs center) is handled by Main.tsx which branches on style=="title".
    """
    title = cast(TitleOverlay, overlay)
    props = TextStyle(font_size=96, font_weight=800, color="#FFFFFF")
    layer = TextLayer(
        start=title.start,
        end=title.end,
        z=title.z,
        runs=[TextRun(text=title.text)],
        style="title",
        props=props,
    )
    return OverlayFragment(layers=(layer,))
