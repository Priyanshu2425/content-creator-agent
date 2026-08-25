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
    """A span of caption text. `emphasis` marks a statically-bold word; `start`/`end` (absolute
    seconds) give the word's spoken window so the backend can highlight the word being said *now*
    (karaoke). Both timings are None for a static run (a title, or a plain single-cue caption)."""

    text: str
    emphasis: bool = False
    start: float | None = None
    end: float | None = None


class TextStyle(_Model):
    """The ``generic`` caption renderer's visual params (ADR 0010), carried by a ``text`` layer.

    No longer a universal field: this is the param schema of the one ``generic`` caption renderer
    that ``pill``/``word-bold``/``kinetic`` configure (ADR 0010 amends ADR 0002 for captions). The
    backend's ``generic`` component paints from these primitive fields, keyed by the layer's
    ``style`` id through the caption renderer registry. ``background`` is ``None`` for styles with
    no pill; sizes/paddings are in pixels at the IR canvas scale. The pop-in *animation* of kinetic
    is not here -- it rides the layer's ``opacity`` and ``transform.scale`` tracks, evaluated per
    frame by the keyframe sampler.
    """

    font_size: int = Field(gt=0)  # px at the IR canvas scale
    font_weight: int = Field(ge=100, le=900)
    color: str  # text fill, CSS color string
    background: str | None = None  # pill fill, CSS color string; None = no pill
    border_radius: int = Field(default=0, ge=0)  # px; the pill's rounding
    padding_x: int = Field(default=0, ge=0)  # px; horizontal padding inside the pill
    padding_y: int = Field(default=0, ge=0)  # px; vertical padding inside the pill
    highlight_color: str | None = None  # active-word fill for karaoke runs; None = no highlight


class HighlightBoxStyle(_Model):
    """The ``highlight-box`` caption renderer's visual params (ADR 0010), carried by a ``text`` layer.

    The first net-new caption renderer beyond the generic karaoke look: words split into separate
    wrapping highlighter boxes, each with a small rotation jitter and a per-word spring pop as its
    spoken window opens. Unlike ``TextStyle`` (the generic renderer's schema) these are the fields
    *this* renderer paints from -- distinct param schemas per renderer is exactly the openness ADR
    0010 buys. The renderer owns its own box grouping/animation; the per-word pop is driven by each
    run's spoken window in the component (not the layer opacity/scale tracks), so the layer carries
    no animation tracks for this style.
    """

    font_size: int = Field(gt=0)  # px at the IR canvas scale
    font_weight: int = Field(ge=100, le=900)
    text_color: str  # the word text fill, CSS color string
    box_colors: list[str] = Field(min_length=1)  # highlighter box fills, cycled across words
    box_radius: int = Field(default=0, ge=0)  # px; each box's corner rounding
    padding_x: int = Field(default=0, ge=0)  # px; horizontal padding inside each box
    padding_y: int = Field(default=0, ge=0)  # px; vertical padding inside each box
    rotation_jitter_deg: float = Field(default=0.0, ge=0.0)  # max absolute per-box rotation
    pop_seconds: float = Field(default=0.0, ge=0.0)  # per-word spring pop window; 0 = no pop
    pop_start_scale: float = Field(default=1.0, gt=0.0)  # scale at the start of a word's pop


class TikTokStyle(_Model):
    """The ``tiktok`` caption renderer's visual params (ADR 0010), carried by a ``text`` layer.

    A port of Remotion's TikTok captions template: heavy uppercase-ready text with a thick black
    stroke (``paintOrder: stroke``), the whole line popping in (scale + rise) and the word being
    spoken *now* recoloured to ``active_color`` (the template's bright green). Its own param schema,
    distinct from the generic ``TextStyle`` and the ``HighlightBoxStyle`` -- the renderer owns the
    per-line enter spring and the active-word highlight, so the layer carries no animation tracks.
    """

    font_size: int = Field(gt=0)  # px at the IR canvas scale
    font_weight: int = Field(ge=100, le=900)
    color: str  # inactive word fill, CSS color string
    active_color: str  # the word being spoken now, CSS color string
    stroke_width: int = Field(default=0, ge=0)  # px; black outline thickness (0 = no stroke)
    stroke_color: str = "#000000"  # outline colour, CSS color string
    pop_seconds: float = Field(default=0.0, ge=0.0)  # line enter-spring window; 0 = no pop
    pop_start_scale: float = Field(default=1.0, gt=0.0)  # scale at the start of the enter
    pop_translate_y: int = Field(default=0, ge=0)  # px the line rises from during the enter


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
    crop: Rect | None = None  # source sub-rect to show (normalized); None = whole source (cover)


class TextLayer(_Layer):
    kind: Literal["text"] = "text"
    runs: list[TextRun] = Field(min_length=1)
    # The caption style id is now *authoritative*: the backend dispatches this layer to the caption
    # renderer registered under this id (ADR 0010). `"title"` is the text-hook overlay's own
    # renderer (not a caption). `params` are that renderer's typed params (the generic TextStyle).
    style: str
    # The renderer's typed params the backend paints from. Each caption renderer has its own param
    # schema (ADR 0010): `generic` (pill/word-bold/kinetic) paints from `TextStyle`, `highlight-box`
    # from `HighlightBoxStyle`, `tiktok` from `TikTokStyle`. The union is the kernel-side set of
    # renderer param schemas; each has `extra="forbid"` so a params dict resolves unambiguously.
    params: TextStyle | HighlightBoxStyle | TikTokStyle


class AudioLayer(_Layer):
    kind: Literal["audio"] = "audio"
    src: str
    in_point: float | None = Field(default=None, alias="in", ge=0)


class HookLayer(_Layer):
    """The opening text-hook, always painted via a backend renderer (the Remotion CenterHookCard).

    Carries *semantic, backend-neutral* params -- the words and the look -- not an animation or a
    component name, so a non-Remotion backend can paint it differently (ADR 0002, the way captions
    carry a style id). The cursor/click animation is owned by the renderer, not the IR.
    """

    kind: Literal["hook"] = "hook"
    text: str
    text_color: str = "#0A0A0A"
    box_color: str = "#FF6B35"
    brand: str = "buildspace labs"
    placement: Literal["top", "center"] = "top"


# The kinds a backend interprets. Adding a kind is the deliberate, all-backends-touching change
# ADR 0002 anticipates -- not something to grow casually.
Layer = Annotated[
    MediaLayer | TextLayer | AudioLayer | HookLayer,
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
