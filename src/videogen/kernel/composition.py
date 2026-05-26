"""Pydantic models: Composition, Asset, Audio, Scene, Ref, Transition, Overlay, Caption.

The authored, declarative document (ADR 0001) and the message contract between the three
services (ADR 0003). Field names and discriminator values follow CONTEXT.md exactly. Pure
data + per-model field validation only -- no Builder, compiler, validator, or render logic.
Cross-cutting checks (scene overlap, gaps, region validity, caption alignment) are Phase 4.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class TransitionKind(StrEnum):
    """Non-cut boundaries only; a cut is the default and is never authored."""

    crossfade = "crossfade"


class _Model(BaseModel):
    # extra=forbid rejects unknown/misspelled fields; populate_by_name lets Python use the
    # field name while JSON carries the glossary alias (e.g. `in`, `afterScene`).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- assets & references ---


class Asset(_Model):
    """A media source declared once in the library as `id -> {type, src}`; id is the key."""

    type: AssetType
    src: str


class Ref(_Model):
    """A reference to an Asset by id, optionally carrying an in-point (source-time offset).

    On-screen duration comes from the holding span (the Scene), not from the Reference.
    """

    asset: AssetId
    in_point: float | None = Field(default=None, alias="in", ge=0)


class Audio(_Model):
    """The Voiceover: a reference to an audio Asset; the master clock (ADR 0005)."""

    asset: AssetId


# --- scenes & transitions ---


class Scene(_Model):
    """Owns the base layer for a contiguous span; picks one Layout, fills each Region."""

    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    layout: LayoutName
    regions: dict[RegionName, Ref] = Field(default_factory=dict)


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
    type: Literal["zoom"] = "zoom"


class PanOverlay(TransformOverlay):
    type: Literal["pan"] = "pan"


class InsertOverlay(AdditiveOverlay):
    type: Literal["insert"] = "insert"


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
