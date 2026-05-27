"""`insert` overlay contract: classification, param validation, registry entry (Phase 6).

The one *additive* effect: it declares itself additive so the compile path paints it into the
z-ordered stack. It owns the validity of ``scale``/``fade`` (the registry half of two-phase); the
``asset`` reference's existence is checked by the Validator's dangling pass, alongside scenes.
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import InsertOverlay, Overlay
from videogen.kernel.registry import PROBE_ASSET, OverlayContract, OverlayKind, register_overlay
from videogen.plugins.overlays.insert.ir import to_ir


def validate_params(overlay: Overlay) -> list[str]:
    """A card's ``scale`` is a frame-width fraction in (0, 1]; ``fade`` is non-negative seconds."""
    insert = cast(InsertOverlay, overlay)
    errors: list[str] = []
    if not 0.0 < insert.scale <= 1.0:
        errors.append(f"insert scale {insert.scale} must be in the half-open interval (0, 1]")
    if insert.fade < 0.0:
        errors.append(f"insert fade {insert.fade} must be non-negative")
    return errors


CONTRACT = OverlayContract(
    kind=OverlayKind.additive,
    to_ir=to_ir,
    probe=InsertOverlay(start=0.0, end=1.0, asset=PROBE_ASSET),
    validate_params=validate_params,
)
register_overlay("insert", CONTRACT)
