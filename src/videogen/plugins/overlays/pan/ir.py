"""`pan` transform overlay -- pure `to_ir` (Phase 6, ADR 0002).

Emits a neutral transform fragment that translates the target region's existing base content from
its origin to ``(dx, dy)`` over the span, with no net scale change (CONTEXT.md). ``dx``/``dy`` are
fractions of the frame; the compiler-supplied canvas size resolves them to the pixel translate the
IR carries. An axis with no motion emits no track, so a horizontal pan stays a single track. Like
zoom, it paints nothing -- the compiler binds the track onto the base region, not the layers above.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, PanOverlay
from videogen.kernel.ir import Easing, Keyframe, Transform, Value
from videogen.kernel.registry import CompileContext, OverlayFragment


def _track(start: float, end: float, end_value: float) -> Value | None:
    """A 0 -> ``end_value`` (pixels) keyframe track, or ``None`` when the axis does not move."""
    if end_value == 0.0:
        return None
    return Value(
        keyframes=[
            Keyframe(t=start, value=0.0),
            Keyframe(t=end, value=end_value, easing=Easing.ease_in_out),
        ]
    )


def to_ir(overlay: Overlay, ctx: CompileContext) -> OverlayFragment:
    """Compile a pan into translate-track(s) (in pixels) over ``[start, end]``."""
    pan = cast(PanOverlay, overlay)
    transform = Transform(
        translate_x=_track(pan.start, pan.end, pan.dx * ctx.width),
        translate_y=_track(pan.start, pan.end, pan.dy * ctx.height),
    )
    return OverlayFragment(transform=transform)
