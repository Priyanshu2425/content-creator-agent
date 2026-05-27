"""`zoom` overlay contract: classification, param validation, registry entry (Phase 6).

Declares the overlay as a *transform* (so the compile path keeps it out of the paint stack) and
owns the type-specific param validity -- the registry half of the two-phase split (CONTEXT.md
"Envelope"). The pure `to_ir` lives in `ir.py`; this module wires it into the default registry.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, ZoomOverlay
from videogen.kernel.registry import OverlayContract, OverlayKind, register_overlay
from videogen.plugins.overlays.zoom.ir import to_ir


def validate_params(overlay: Overlay) -> list[str]:
    """A zoom's start and end scales must both be positive (a 0 or negative scale is degenerate)."""
    zoom = cast(ZoomOverlay, overlay)
    if zoom.from_scale <= 0.0 or zoom.to_scale <= 0.0:
        return [f"zoom scales must be positive (got from={zoom.from_scale}, to={zoom.to_scale})"]
    return []


CONTRACT = OverlayContract(
    kind=OverlayKind.transform,
    to_ir=to_ir,
    probe=ZoomOverlay(start=0.0, end=1.0),
    validate_params=validate_params,
)
register_overlay("zoom", CONTRACT)
