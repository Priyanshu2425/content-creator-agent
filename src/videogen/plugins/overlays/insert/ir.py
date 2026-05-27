"""`insert` additive overlay -- pure `to_ir` (Phase 6, ADR 0002).

The floating-b-roll form (CONTEXT.md): a card painted over a continuing scene, as distinct from
full-frame b-roll (a `full` scene). Emits exactly one painted `media` layer -- the only effect that
joins the z-ordered paint stack -- positioned by ``anchor`` + ``scale`` into a normalized rect, with
an optional opacity ramp for ``fade``. The card is square in pixels on the 9:16 frame (width is the
given fraction of frame width; height matches in pixels via the canvas aspect). No transform is
emitted: an insert is additive, not a reshaping of base content.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Anchor, InsertOverlay, Overlay
from videogen.kernel.ir import Easing, Keyframe, MediaLayer, Rect, Value, constant
from videogen.kernel.registry import CompileContext, OverlayFragment, media_content

# Inset from the frame edge for a corner-anchored card, as a fraction of the frame.
MARGIN = 0.04


def _card_rect(anchor: Anchor, scale: float, width: int, height: int) -> Rect:
    """Place a square card of width ``scale`` (frame fraction) at ``anchor`` with an edge margin."""
    w = scale
    h = scale * (width / height)  # square in pixels on the 9:16 frame
    m = MARGIN
    positions: dict[Anchor, tuple[float, float]] = {
        Anchor.top_left: (m, m),
        Anchor.top_right: (1.0 - w - m, m),
        Anchor.bottom_left: (m, 1.0 - h - m),
        Anchor.bottom_right: (1.0 - w - m, 1.0 - h - m),
        Anchor.center: ((1.0 - w) / 2.0, (1.0 - h) / 2.0),
    }
    x, y = positions[anchor]
    return Rect(x=max(0.0, x), y=max(0.0, y), width=min(w, 1.0), height=min(h, 1.0))


def _fade(insert: InsertOverlay) -> Value | None:
    """An opacity ramp 0 -> 1 -> 0 over a ``fade``-second window at each end (``None`` if no fade).

    The ramp window is clamped to half the span so the card is fully visible by mid-span.
    """
    if insert.fade <= 0.0:
        return None
    window = min(insert.fade, (insert.end - insert.start) / 2.0)
    return Value(
        keyframes=[
            Keyframe(t=insert.start, value=0.0),
            Keyframe(t=insert.start + window, value=1.0, easing=Easing.ease_out),
            Keyframe(t=insert.end - window, value=1.0),
            Keyframe(t=insert.end, value=0.0, easing=Easing.ease_in),
        ]
    )


def to_ir(overlay: Overlay, ctx: CompileContext) -> OverlayFragment:
    """Compile an insert into one painted media layer placed by ``anchor`` + ``scale``."""
    insert = cast(InsertOverlay, overlay)
    asset = ctx.assets[insert.asset]
    layer = MediaLayer(
        start=insert.start,
        end=insert.end,
        z=insert.z,
        opacity=_fade(insert) or constant(1.0),
        src=asset.src,
        content=media_content(asset),
        in_point=insert.in_point,
        rect=_card_rect(insert.anchor, insert.scale, ctx.width, ctx.height),
    )
    return OverlayFragment(layers=(layer,))
