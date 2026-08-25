"""The ``highlight-box`` caption renderer's param schema (ADR 0010).

The first net-new caption renderer's validation schema: the fields an author (or the
creative-direction agent) may set, with defaults reproducing the seed ``HighlightCaptions`` look
(neon highlighter boxes, slight rotation jitter, a per-word spring pop). These validated params
compile straight to the kernel ``HighlightBoxStyle`` the backend paints from -- distinct from the
``generic`` renderer's ``TextStyle`` schema, which is the whole point of the registry (ADR 0010).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HighlightBoxParams(BaseModel):
    """Typed params of the ``highlight-box`` caption renderer (the highlighter-box look)."""

    model_config = ConfigDict(extra="forbid")

    font_size: int = Field(default=84, gt=0)  # px at the IR canvas scale
    font_weight: int = Field(default=800, ge=100, le=900)
    text_color: str = "#0B0B0B"  # word text fill (dark on the bright box), CSS color
    box_colors: list[str] = Field(
        default_factory=lambda: ["#FFE14D", "#7CF6A0", "#6FD3FF", "#FF9FB2"], min_length=1
    )  # highlighter box fills, cycled across words
    box_radius: int = Field(default=10, ge=0)  # px; each box's corner rounding
    padding_x: int = Field(default=18, ge=0)  # px; horizontal padding inside each box
    padding_y: int = Field(default=6, ge=0)  # px; vertical padding inside each box
    rotation_jitter_deg: float = Field(default=4.0, ge=0.0)  # max absolute per-box rotation
    pop_seconds: float = Field(default=0.18, ge=0.0)  # per-word spring pop window; 0 = no pop
    pop_start_scale: float = Field(default=0.6, gt=0.0)  # scale at the start of a word's pop
