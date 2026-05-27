"""Resolver: ``(composition, t) -> frame description``, plus a whole-Composition textual timeline.

The Resolver is the authoring agent's cheapest, always-available sense (ADR 0004): it answers
"what is on screen at ``t``" without a render, and renders a human- and agent-readable timeline for
sanity-checking the edit. It derives state purely from the declarative document at ``t`` (ADR 0001)
-- it reads the scenes/overlays/captions whose spans contain ``t``, never replaying an operation
stream -- so resolution is total, seek-cheap, and independent of how the document was built.

Spans are half-open ``[start, end)``: at a boundary the later thing owns the instant. At any ``t``
at most one Scene owns the base layer; if none does, the frame is **black** (a gap). Overlays and
captions are resolved independently of the base Scene, because in a gap they still composite over
the black (CONTEXT.md coverage rules). Only *additive* things (additive overlays + captions) enter
the paint stack; a *transform* overlay (zoom/pan) is reported as active but is never painted.

Pure kernel: reads only the Phase 1 contract types, with no service or backend dependency
(ADR 0003).
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.kernel.composition import (
    AdditiveOverlay,
    AssetId,
    Caption,
    CaptionStyle,
    Composition,
    LayoutName,
    Overlay,
    RegionName,
    Scene,
)

# Deterministic region ordering for region fills and the timeline, by the enum's declared order.
_REGION_ORDER = {region: index for index, region in enumerate(RegionName)}


@dataclass(frozen=True)
class RegionFill:
    """What fills one Region of the owning Scene: the referenced Asset and its optional in-point."""

    region: RegionName
    asset: AssetId
    in_point: float | None


@dataclass(frozen=True)
class ActiveOverlay:
    """An overlay active at ``t``. ``additive`` overlays are painted; transform overlays are not."""

    type: str
    target: RegionName
    z: int
    additive: bool


@dataclass(frozen=True)
class ActiveCaption:
    """A caption cue active at ``t`` on the dedicated captions track (always painted)."""

    text: str
    style: CaptionStyle
    z: int


@dataclass(frozen=True)
class PaintedThing:
    """One entry in the paint stack -- an additive overlay or a caption -- ordered by ``z``."""

    kind: str  # "overlay" | "caption"
    label: str  # overlay type, or caption text
    z: int


@dataclass(frozen=True)
class FrameState:
    """Everything on screen at one instant: the base Scene (or black), and the things over it."""

    t: float
    scene_id: str | None  # None => a gap: the base layer is black at t
    layout: LayoutName | None
    regions: tuple[RegionFill, ...]
    overlays: tuple[ActiveOverlay, ...]
    captions: tuple[ActiveCaption, ...]

    @property
    def is_black(self) -> bool:
        """True when no Scene owns the base layer at ``t`` (a gap renders black)."""
        return self.scene_id is None

    @property
    def paint_order(self) -> tuple[PaintedThing, ...]:
        """The paint stack bottom -> top: additive overlays + captions, sorted ascending by ``z``.

        Sort is stable, so ties keep overlays before captions (and captions sit on top by their
        high-``z`` convention). Transform overlays are excluded -- they reshape a base region and
        never enter the paint stack (CONTEXT.md).
        """
        painted = [
            PaintedThing("overlay", overlay.type, overlay.z)
            for overlay in self.overlays
            if overlay.additive
        ]
        painted += [PaintedThing("caption", caption.text, caption.z) for caption in self.captions]
        return tuple(sorted(painted, key=lambda thing: thing.z))


def _active(start: float, end: float, t: float) -> bool:
    """Half-open containment: ``start <= t < end``."""
    return start <= t < end


def _region_fills(scene: Scene) -> tuple[RegionFill, ...]:
    fills = [
        RegionFill(region=region, asset=ref.asset, in_point=ref.in_point)
        for region, ref in scene.regions.items()
    ]
    fills.sort(key=lambda fill: _REGION_ORDER.get(fill.region, len(_REGION_ORDER)))
    return tuple(fills)


def resolve(composition: Composition, t: float) -> FrameState:
    """Derive the frame description at absolute time ``t`` from the declarative document."""
    scene = next((s for s in composition.scenes if _active(s.start, s.end, t)), None)

    overlays = tuple(
        ActiveOverlay(
            type=overlay.type,
            target=overlay.target,
            z=overlay.z,
            additive=isinstance(overlay, AdditiveOverlay),
        )
        for overlay in composition.overlays
        if _active(overlay.start, overlay.end, t)
    )
    captions = tuple(
        ActiveCaption(text=caption.text, style=caption.style, z=caption.z)
        for caption in composition.captions
        if _active(caption.start, caption.end, t)
    )

    if scene is None:
        return FrameState(
            t=t, scene_id=None, layout=None, regions=(), overlays=overlays, captions=captions
        )
    return FrameState(
        t=t,
        scene_id=scene.id,
        layout=scene.layout,
        regions=_region_fills(scene),
        overlays=overlays,
        captions=captions,
    )


def timeline(composition: Composition, *, duration: float) -> str:
    """Render the whole Composition as a textual timeline: base-layer spans (gaps shown as black),
    then the captions and overlays laid over them. The agent's first, cheapest perception channel
    (ADR 0004) and a human sanity-check of the edit."""
    lines = [f"Timeline (0.00-{duration:.2f}s)", "base layer:"]

    cursor = 0.0
    for scene in sorted(composition.scenes, key=lambda s: (s.start, s.end)):
        if scene.start > cursor:
            lines.append(f"  [{cursor:.2f}-{scene.start:.2f}] black (gap)")
        fills = " ".join(
            f"{fill.region.value}={fill.asset}"
            + (f"@{fill.in_point:.2f}" if fill.in_point is not None else "")
            for fill in _region_fills(scene)
        )
        lines.append(
            f"  [{scene.start:.2f}-{scene.end:.2f}] scene {scene.id} "
            f"· {scene.layout.value} · {fills or '(empty)'}"
        )
        cursor = max(cursor, scene.end)
    if cursor < duration:
        lines.append(f"  [{cursor:.2f}-{duration:.2f}] black (gap, trailing tail)")

    if composition.captions:
        lines.append("captions:")
        lines.extend(_caption_line(caption) for caption in composition.captions)

    if composition.overlays:
        lines.append("overlays:")
        lines.extend(_overlay_line(overlay) for overlay in composition.overlays)

    return "\n".join(lines)


def _caption_line(caption: Caption) -> str:
    return (
        f"  [{caption.start:.2f}-{caption.end:.2f}] {caption.style.value} "
        f"(z{caption.z}) \"{caption.text}\""
    )


def _overlay_line(overlay: Overlay) -> str:
    kind = "additive" if isinstance(overlay, AdditiveOverlay) else "transform"
    return (
        f"  [{overlay.start:.2f}-{overlay.end:.2f}] {overlay.type} -> "
        f"{overlay.target.value} ({kind}, z{overlay.z})"
    )
