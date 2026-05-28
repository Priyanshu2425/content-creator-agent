"""`full` layout: one Region named `full` filling the whole frame (ADR 0001, Phase 5).

The simplest arrangement -- a single talking-head or a full-frame b-roll cut. Its `to_ir` places the
`full` Region's Reference as a full-frame `media` Layer (``rect=None``), so it renders through the
exact same neutral IR path as every other Layout. Backend-agnostic: a contract plus a pure `to_ir`,
no render dependency (ADR 0002).
"""

from __future__ import annotations

from videogen.kernel.composition import LayoutName, RegionName, Scene
from videogen.kernel.ir import Layer, MediaLayer
from videogen.kernel.registry import (
    CompileContext,
    LayoutContract,
    media_content,
    media_crop,
    register_layout,
)

REGIONS = frozenset({RegionName.full})


def to_ir(scene: Scene, ctx: CompileContext) -> list[Layer]:
    """Place the `full` Region as a single full-frame media layer spanning the Scene."""
    ref = scene.regions.get(RegionName.full)
    if ref is None:
        return []
    asset = ctx.assets[ref.asset]
    return [
        MediaLayer(
            start=scene.start,
            end=scene.end,
            z=0,
            src=asset.src,
            content=media_content(asset),
            in_point=ref.in_point,
            rect=None,  # full frame
            crop=media_crop(ref),
        )
    ]


CONTRACT = LayoutContract(regions=REGIONS, to_ir=to_ir)
register_layout(LayoutName.full, CONTRACT)
