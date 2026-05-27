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


class Rect(_Model):
    """A media layer's destination box, as normalized [0,1] fractions of the frame.

    Geometry is owned by the layout preset (ADR 0001), compiled into this neutral rect so the
    backend places the media from data without knowing any layout by name. Normalized rather than
    pixel so it is independent of the IR canvas size. `None` on a layer means the whole frame.
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class TextRun(_Model):
    """A span of caption text; `emphasis` marks the word-bold / kinetic key word."""

    text: str
    emphasis: bool = False


class TextStyle(_Model):
    """Visual properties of a caption, baked by the compiler from a caption-style preset.

    The compiler encodes each known style (pill / word-bold / kinetic) into these primitive
    fields so the backend paints from data and never branches on the style name (ADR 0002).
    `background` is `None` for styles with no pill; sizes/paddings are in pixels at the IR canvas
    scale. The pop-in *animation* of `kinetic` is not here -- it rides the layer's `opacity` and
    `transform.scale` tracks, evaluated per frame by the keyframe sampler.
    """

    font_size: int = Field(gt=0)  # px at the IR canvas scale
    font_weight: int = Field(ge=100, le=900)
    color: str  # text fill, CSS color string
    background: str | None = None  # pill fill, CSS color string; None = no pill
    border_radius: int = Field(default=0, ge=0)  # px; the pill's rounding
    padding_x: int = Field(default=0, ge=0)  # px; horizontal padding inside the pill
    padding_y: int = Field(default=0, ge=0)  # px; vertical padding inside the pill


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
    content: Literal["video", "image"] = "video"  # how the backend paints it (clip vs still)
    in_point: float | None = Field(default=None, alias="in", ge=0)
    rect: Rect | None = None  # destination box (normalized); None = full frame


class TextLayer(_Layer):
    kind: Literal["text"] = "text"
    runs: list[TextRun] = Field(min_length=1)
    style: str  # caption-style name carried through as provenance; the backend never branches on it
    props: TextStyle  # the compiled visual properties the backend actually paints from


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
