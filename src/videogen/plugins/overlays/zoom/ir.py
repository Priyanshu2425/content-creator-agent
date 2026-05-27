"""`zoom` transform overlay -- pure `to_ir` (Phase 6, ADR 0002).

Emits a neutral transform fragment: a single `scale` keyframe track interpolating ``from_scale ->
to_scale`` over the overlay's span, eased to a settle. It paints no layer -- the compiler binds this
track onto the existing base content of the target region, so the zoom reshapes that region and
never scales the captions or inserts above it (CONTEXT.md). Easing reuses the IR vocabulary the
kinetic captions established (Phase 3), so one keyframe sampler drives captions and effects alike.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, ZoomOverlay
from videogen.kernel.ir import Easing, Keyframe, Transform, Value
from videogen.kernel.registry import CompileContext, OverlayFragment


def to_ir(overlay: Overlay, ctx: CompileContext) -> OverlayFragment:
    """Compile a zoom into a scale-track transform fragment over ``[start, end]``."""
    zoom = cast(ZoomOverlay, overlay)
    scale = Value(
        keyframes=[
            Keyframe(t=zoom.start, value=zoom.from_scale),
            Keyframe(t=zoom.end, value=zoom.to_scale, easing=Easing.ease_in_out),
        ]
    )
    return OverlayFragment(transform=Transform(scale=scale))
