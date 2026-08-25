"""The ``generic`` caption renderer's param schema (ADR 0010).

The flat IR ``TextStyle`` is no longer a universal field; it is the param schema of this one
renderer -- the original karaoke painter that ``pill``/``word-bold``/``kinetic`` configure. The
params are the visual props the backend paints plus the emphasis flag and the kinetic pop-in
controls (which compile to the layer's ``opacity``/``transform.scale`` keyframe tracks -- no
per-style animation code). Each built-in style is the same renderer with different param defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenericCaptionParams(BaseModel):
    """Typed params of the ``generic`` caption renderer (the karaoke look's full configuration).

    The visual block mirrors the former flat ``TextStyle`` so the migrated styles paint identically.
    ``emphasis`` marks a single-cue caption's word statically bold (``word-bold``/``kinetic`` set
    it; ``pill`` does not). ``pop_seconds``/``pop_start_scale`` drive the pop-in: ``pop_seconds`` 0
    means no animation (``pill``/``word-bold``), a positive value springs opacity 0->1 and scale
    up to 1 over a short window from the caption start (``kinetic``).
    """

    model_config = ConfigDict(extra="forbid")

    # --- visual props (the former flat TextStyle, now this renderer's schema) ---
    font_size: int = Field(gt=0)  # px at the IR canvas scale
    font_weight: int = Field(ge=100, le=900)
    color: str  # text fill, CSS color string
    background: str | None = None  # pill fill, CSS color string; None = no pill
    border_radius: int = Field(default=0, ge=0)  # px; the pill's rounding
    padding_x: int = Field(default=0, ge=0)  # px; horizontal padding inside the pill
    padding_y: int = Field(default=0, ge=0)  # px; vertical padding inside the pill
    highlight_color: str | None = None  # active-word fill for karaoke runs; None = no highlight

    # --- behavior ---
    emphasis: bool = False  # single out the cue's key word (statically bold) for a plain cue
    pop_seconds: float = Field(default=0.0, ge=0.0)  # pop-in window; 0 = no animation
    pop_start_scale: float = Field(default=1.0, gt=0.0)  # scale at the start of the pop-in
