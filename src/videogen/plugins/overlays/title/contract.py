"""`title` overlay contract: classification, param validation, registry entry (texthook/01).

An *additive* text effect (the text hook): it declares itself additive so the compile path paints it
into the z-ordered stack. It owns the validity of its ``text`` (the registry half of two-phase).
"""

from __future__ import annotations

from typing import cast

from videogen.kernel.composition import Overlay, TitleOverlay
from videogen.kernel.registry import OverlayContract, OverlayKind, register_overlay
from videogen.plugins.overlays.title.ir import to_ir


def validate_params(overlay: Overlay) -> list[str]:
    """A title must carry non-empty text."""
    title = cast(TitleOverlay, overlay)
    if not title.text.strip():
        return ["title text must not be empty"]
    return []


CONTRACT = OverlayContract(
    kind=OverlayKind.additive,
    to_ir=to_ir,
    probe=TitleOverlay(start=0.0, end=1.0, text="probe"),
    validate_params=validate_params,
)
register_overlay("title", CONTRACT)
