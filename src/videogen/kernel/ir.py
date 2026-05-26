"""Neutral IR: Layer (media|text|audio), common fields, Value/Keyframe track, easing.

What a Composition compiles into for rendering (ADR 0002). Every backend interprets the three
layer kinds, never per-overlay-type code; adding an overlay never touches a backend. Serializes
to JSON so it can be passed to the Remotion subprocess as `--props`. Pure data only -- the
compiler (compile_ir) and the backends that consume this live in later phases.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- animation vocabulary ---


class Easing(StrEnum):
    linear = "linear"
    ease_in = "ease_in"
    ease_out = "ease_out"
    ease_in_out = "ease_in_out"


class Keyframe(_Model):
    t: float = Field(ge=0)  # absolute seconds
    value: float
    easing: Easing = Easing.linear


class Value(_Model):
    """A possibly-animated scalar; a single keyframe means a constant value."""

    keyframes: list[Keyframe] = Field(min_length=1)


def constant(value: float) -> Value:
    """A non-animated Value: one keyframe at t=0."""
    return Value(keyframes=[Keyframe(t=0.0, value=value)])


class Transform(_Model):
    """Keyframed transform tracks: zoom compiles to `scale`, pan to `translate_*` (ADR 0002)."""

    scale: Value | None = None
    translate_x: Value | None = None
    translate_y: Value | None = None


class TextRun(_Model):
    """A span of caption text; `emphasis` marks the word-bold / kinetic key word."""

    text: str
    emphasis: bool = False


# --- layers: common fields + discriminated union on `kind` ---


class _Layer(_Model):
    """Common fields every backend interprets, regardless of layer kind."""

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    z: int = 0
    opacity: Value = Field(default_factory=lambda: constant(1.0))
    transform: Transform | None = None


class MediaLayer(_Layer):
    kind: Literal["media"] = "media"
    src: str  # resolved media path/source
    in_point: float | None = Field(default=None, alias="in", ge=0)


class TextLayer(_Layer):
    kind: Literal["text"] = "text"
    runs: list[TextRun] = Field(min_length=1)
    style: str  # caption-style name carried through (e.g. pill / word-bold / kinetic)


class AudioLayer(_Layer):
    kind: Literal["audio"] = "audio"
    src: str
    in_point: float | None = Field(default=None, alias="in", ge=0)


# The three kinds a backend interprets. Adding a kind is the deliberate, all-backends-touching
# change ADR 0002 anticipates -- not something to grow casually.
Layer = Annotated[
    MediaLayer | TextLayer | AudioLayer,
    Field(discriminator="kind"),
]


# --- root ---


class IR(_Model):
    """Backend-agnostic render IR: canvas params + a flat, timed list of layers (ADR 0002)."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    duration: float = Field(gt=0)  # seconds; set by the voiceover (master clock)
    layers: list[Layer] = Field(default_factory=list)
