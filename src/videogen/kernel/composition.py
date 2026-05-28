"""Pydantic models: Composition, Asset, Audio, Scene, Ref, Transition, Overlay, Caption.

The authored, declarative document (ADR 0001) and the message contract between the three
services (ADR 0003). Field names and discriminator values follow CONTEXT.md exactly. Pure
data + per-model field validation only -- no Builder, compiler, validator, or render logic.
Cross-cutting checks (scene overlap, gaps, region validity, caption alignment) are Phase 4.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssetId = str


# --- enumerations (values are glossary-binding; Python names use underscores) ---


class AssetType(StrEnum):
    video = "video"
    image = "image"
    audio = "audio"


class LayoutName(StrEnum):
    """Known built-in layouts; the registry replaces this fixed set in Phase 5 (additively)."""

    full = "full"
    split_h = "split-h"


class RegionName(StrEnum):
    """Frame regions a layout exposes and effects target (purely spatial)."""

    full = "full"
    top = "top"
    bottom = "bottom"


class CaptionStyle(StrEnum):
    pill = "pill"
    word_bold = "word-bold"
    kinetic = "kinetic"


class Anchor(StrEnum):
    """Where an `insert` card sits on the frame, by intent rather than raw pixels (CONTEXT.md)."""

    top_left = "top-left"
    top_right = "top-right"
    bottom_left = "bottom-left"
    bottom_right = "bottom-right"
    center = "center"  # type: ignore[assignment]  # member name shadows str.center


class TransitionKind(StrEnum):
    """Non-cut boundaries only; a cut is the default and is never authored."""

    crossfade = "crossfade"
    whoosh = "whoosh"  # hard visual cut + whoosh SFX at the boundary (audio wired in later)


class _Model(BaseModel):
    # extra=forbid rejects unknown/misspelled fields; populate_by_name lets Python use the
    # field name while JSON carries the glossary alias (e.g. `in`, `afterScene`).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- assets & references ---


class Asset(_Model):
    """A media source declared once in the library as `id -> {type, src}`; id is the key."""

    type: AssetType
    src: str


class CropRect(_Model):
    """A normalized source sub-rectangle of an asset, in [0,1] fractions of the source's own frame.

    When set on a region fill, only this window of the source is shown (then scaled to cover the
    region's destination box), instead of the default centered cover. The window must lie inside the
    source: ``x + width <= 1`` and ``y + height <= 1``.
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _within_source(self) -> "CropRect":
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError(
                f"crop window must lie within the source: got x+width={self.x + self.width}, "
                f"y+height={self.y + self.height} (both must be <= 1)"
            )
        return self


class Ref(_Model):
    """A reference to an Asset by id, optionally carrying an in-point (source-time offset).

    On-screen duration comes from the holding span (the Scene), not from the Reference. ``crop``
    optionally narrows which sub-rectangle of the source is shown in the region (see ``CropRect``).
    """

    asset: AssetId
    in_point: float | None = Field(default=None, alias="in", ge=0)
    crop: CropRect | None = None


class Audio(_Model):
    """The Voiceover: a reference to an audio Asset; the master clock (ADR 0005)."""

    asset: AssetId


# --- scenes & transitions ---


class Scene(_Model):
    """Owns the base layer for a contiguous span; picks one Layout, fills each Region.

    ``layout_params`` carries the chosen Layout's named preset parameters (e.g. ``split-h``'s
    ``ratio``) -- never free-form geometry (ADR 0001). The Layout's registry contract owns what the
    keys mean and validates them; an unknown Layout adds keys without a schema change.
    """

    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    layout: LayoutName
    regions: dict[RegionName, Ref] = Field(default_factory=dict)
    layout_params: dict[str, float] = Field(default_factory=dict)


class Transition(_Model):
    """A non-cut boundary, keyed by the scene it follows (stable id, never absolute time)."""

    after_scene: str = Field(alias="afterScene")
    kind: TransitionKind
    duration: float = Field(default=0.5, ge=0)


# --- overlays: shared Envelope + discriminated union on `type` ---


class _Overlay(_Model):
    """Envelope: the type-agnostic fields every overlay shares (two-phase validation).

    Type-specific params are deferred to the registry in Phase 5; the Envelope split is
    established here.
    """

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    target: RegionName = RegionName.full
    z: int = 0


class TransformOverlay(_Overlay):
    """Reshapes its target base region; never painted, never scales the layers above it."""


class AdditiveOverlay(_Overlay):
    """Painted on top; participates in the z paint stack."""


class ZoomOverlay(TransformOverlay):
    """Slow zoom on the target region: scale interpolates ``from_scale -> to_scale`` over the span.

    The numeric ranges are validated by the zoom plugin's registry contract (the type-specific half
    of the two-phase split, CONTEXT.md "Envelope"), not by the fixed envelope schema.
    """

    type: Literal["zoom"] = "zoom"
    from_scale: float = 1.0  # scale at the overlay's start
    to_scale: float = 1.2  # scale at the overlay's end


class PanOverlay(TransformOverlay):
    """Pan across the target region: translate moves from origin to ``(dx, dy)`` over the span.

    ``dx``/``dy`` are signed fractions of the frame, resolved to pixels by the compiler; their range
    is validated by the pan plugin's registry contract.
    """

    type: Literal["pan"] = "pan"
    dx: float = 0.1  # horizontal end-offset, fraction of frame
    dy: float = 0.0  # vertical end-offset, fraction of frame


class InsertOverlay(AdditiveOverlay):
    """Floating b-roll card painted over a continuing scene, placed by ``anchor`` + ``scale``.

    Carries its own ``asset`` Reference (unlike a transform overlay, which acts on existing base
    content), an optional source ``in``-point, and an optional ``fade`` (seconds) for an opacity
    ramp in and out. ``scale``/``fade`` ranges are validated by the insert plugin's registry
    contract; ``asset`` presence is checked by the Validator's dangling-reference pass.
    """

    type: Literal["insert"] = "insert"
    asset: AssetId  # required: the media painted as the card
    anchor: Anchor = Anchor.top_right
    scale: float = 0.3  # card width as a fraction of the frame width
    in_point: float | None = Field(default=None, alias="in", ge=0)
    fade: float = 0.0  # opacity ramp in/out, seconds


# Adding an action = adding a member here (registry-driven in Phase 5); the Envelope is fixed.
# An unknown `type` fails discriminator validation -> error by default (strict mode).
Overlay = Annotated[
    ZoomOverlay | PanOverlay | InsertOverlay,
    Field(discriminator="type"),
]


# --- captions (dedicated track, not overlays) ---


class Caption(_Model):
    """A transcript-synced text cue on the dedicated `captions` track."""

    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    style: CaptionStyle = CaptionStyle.pill
    z: int = 100  # high z by convention so captions sit on top


# --- root ---


class Composition(_Model):
    """The whole video document: scenes (base layer) + overlays + captions, on one timeline.

    Serializes to/from JSON losslessly (the contract). Use `by_alias=True` when serializing so
    the wire form carries the glossary keys (`in`, `afterScene`).
    """

    version: int = 1
    strict: bool = True
    assets: dict[AssetId, Asset] = Field(default_factory=dict)
    voiceover: Audio  # required: the master clock defines the composition's duration
    scenes: list[Scene] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list)
    captions: list[Caption] = Field(default_factory=list)
