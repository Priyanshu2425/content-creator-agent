"""`pan` overlay contract: classification, param validation, registry entry (Phase 6).

A *transform* overlay (kept out of the paint stack), owning the validity of its ``dx``/``dy``
offsets -- the registry half of the two-phase split. The pure `to_ir` lives in `ir.py`.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, PanOverlay
from videogen.kernel.registry import OverlayContract, OverlayKind, register_overlay
from videogen.plugins.overlays.pan.ir import to_ir


def validate_params(overlay: Overlay) -> list[str]:
    """A pan's offsets are fractions of the frame, so each must sit within ``[-1, 1]``."""
    pan = cast(PanOverlay, overlay)
    errors: list[str] = []
    for axis, value in (("dx", pan.dx), ("dy", pan.dy)):
        if not -1.0 <= value <= 1.0:
            errors.append(f"pan {axis} {value} must be a frame fraction in [-1, 1]")
    return errors


CONTRACT = OverlayContract(
    kind=OverlayKind.transform,
    to_ir=to_ir,
    probe=PanOverlay(start=0.0, end=1.0),
    validate_params=validate_params,
)
register_overlay("pan", CONTRACT)
