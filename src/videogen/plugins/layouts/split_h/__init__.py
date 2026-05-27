"""`split-h` layout: `top` + `bottom` Regions, divider 50/50 by default, set by `ratio` (Phase 5).

The split-screen hook from the reference video. The divider defaults to an even split and is
weighted by the Scene's ``layout_params['ratio']`` -- the fraction of the frame height the `top`
Region gets (CONTEXT.md). Geometry is owned by this preset, not written per-scene (ADR 0001):
`to_ir` computes each Region's normalized destination rect from `ratio` and places the filled
Region's Reference as a `media` Layer. `validate_params` rejects a `ratio` outside the open
interval (0, 1) so an unrenderable split is caught at authoring time, not at render (story 31).
"""

from __future__ import annotations

from videogen.kernel.composition import LayoutName, RegionName, Scene
from videogen.kernel.ir import Layer, MediaLayer, Rect
from videogen.kernel.registry import CompileContext, LayoutContract, media_content, register_layout

REGIONS = frozenset({RegionName.top, RegionName.bottom})

DEFAULT_RATIO = 0.5
RATIO_KEY = "ratio"

# Deterministic placement order so the emitted layers are stable for the IR snapshots.
_REGION_ORDER = (RegionName.top, RegionName.bottom)


def _ratio(scene: Scene) -> float:
    return scene.layout_params.get(RATIO_KEY, DEFAULT_RATIO)


def _geometry(ratio: float) -> dict[RegionName, Rect]:
    """The preset's two destination rects: `top` gets the upper ``ratio`` of the frame height."""
    return {
        RegionName.top: Rect(x=0.0, y=0.0, width=1.0, height=ratio),
        RegionName.bottom: Rect(x=0.0, y=ratio, width=1.0, height=1.0 - ratio),
    }


def to_ir(scene: Scene, ctx: CompileContext) -> list[Layer]:
    """Place each filled Region as a `media` Layer with the preset's geometry for the Scene span."""
    geometry = _geometry(_ratio(scene))
    layers: list[Layer] = []
    for region in _REGION_ORDER:
        ref = scene.regions.get(region)
        if ref is None:
            continue
        asset = ctx.assets[ref.asset]
        layers.append(
            MediaLayer(
                start=scene.start,
                end=scene.end,
                z=0,
                src=asset.src,
                content=media_content(asset),
                in_point=ref.in_point,
                rect=geometry[region],
            )
        )
    return layers


def validate_params(scene: Scene) -> list[str]:
    """A `ratio` must sit strictly inside (0, 1); 0 or 1 collapses a Region to nothing."""
    ratio = _ratio(scene)
    if not 0.0 < ratio < 1.0:
        return [f"split-h scene '{scene.id}' ratio {ratio} must be in the open interval (0, 1)"]
    return []


def region_rects(scene: Scene) -> dict[RegionName, Rect]:
    """The destination rect of each Region for this Scene -- the geometry an effect targets.

    The same preset geometry ``to_ir`` places the media into, so a transform overlay aimed at
    ``top``/``bottom`` binds to exactly the region the layout drew (single source of truth, ADR
    0001).
    """
    return _geometry(_ratio(scene))


CONTRACT = LayoutContract(
    regions=REGIONS, to_ir=to_ir, validate_params=validate_params, region_rects=region_rects
)
register_layout(LayoutName.split_h, CONTRACT)
