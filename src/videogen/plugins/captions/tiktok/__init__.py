"""The ``tiktok`` caption renderer (ADR 0010): a port of Remotion's TikTok captions template.

Heavy text with a thick black stroke, the line popping in (scale + rise), and the word being spoken
now recoloured to a bright accent green -- the recognisable TikTok auto-caption look. Like every
caption visual it is a registry entry (description + param schema + defaults + pure compile) plus a
TS component, with no change to ``compile_ir`` or the Composition schema.

Importing this package registers the style into the default caption registry, exactly as the
``generic`` and ``highlight_box`` packages do.
"""

from __future__ import annotations

from videogen.plugins.captions.registry import CaptionStyleContract, register_caption_style
from videogen.plugins.captions.tiktok.compile import compile_tiktok
from videogen.plugins.captions.tiktok.params import TikTokParams

register_caption_style(
    "tiktok",
    CaptionStyleContract(
        description=(
            "TikTok captions (Remotion template port): heavy text with a thick black outline, the "
            "line pops in, and the word being spoken now turns bright green. The classic TikTok "
            "auto-caption look."
        ),
        params_model=TikTokParams,
        defaults={},  # the schema's field defaults are the look; overrides may be layered on
        compile=compile_tiktok,
    ),
)

__all__ = ["TikTokParams", "compile_tiktok"]
