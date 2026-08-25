"""The ``tiktok`` caption renderer's param schema (ADR 0010).

A port of Remotion's TikTok captions template (https://www.remotion.dev/templates/tiktok): heavy
text with a thick black stroke, the line popping in (scale + rise), and the word being spoken now
recoloured to a bright accent. Defaults reproduce the template's look (font ~110px, white text,
``#39E508`` active green, a black outline, a short enter spring). These validated params compile
straight to the kernel ``TikTokStyle`` the backend paints from -- a schema distinct from the
``generic`` renderer's ``TextStyle`` and the ``highlight-box`` renderer's schema (ADR 0010).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TikTokParams(BaseModel):
    """Typed params of the ``tiktok`` caption renderer (the TikTok-template karaoke look)."""

    model_config = ConfigDict(extra="forbid")

    font_size: int = Field(default=110, gt=0)  # px at the IR canvas scale
    font_weight: int = Field(default=900, ge=100, le=900)
    color: str = "#FFFFFF"  # inactive word fill, CSS color
    active_color: str = "#39E508"  # the word being spoken now (the template's TikTok green)
    stroke_width: int = Field(default=16, ge=0)  # px; black outline thickness (0 = no stroke)
    stroke_color: str = "#000000"  # outline colour, CSS color
    pop_seconds: float = Field(default=0.2, ge=0.0)  # line enter-spring window; 0 = no pop
    pop_start_scale: float = Field(default=0.8, gt=0.0)  # scale at the start of the enter
    pop_translate_y: int = Field(default=40, ge=0)  # px the line rises from during the enter
