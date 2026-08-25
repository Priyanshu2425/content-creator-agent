"""The ``highlight-box`` caption renderer (ADR 0010) -- the first net-new caption visual.

Proves the caption library is extensible: a brand-new caption look is a registry entry (description +
param schema + defaults + pure compile) plus a TS component, with no change to ``compile_ir``, the
Composition schema, or any other layer kind. Words split into separate wrapping highlighter boxes,
each with a small rotation jitter and a per-word spring pop -- the seed ``HighlightCaptions`` look,
word-reveal only (the seed's handwritten annotation/arrow is out of scope: not transcript-synced).

Importing this package registers the style into the default caption registry, exactly as the
``generic`` package does.
"""

from __future__ import annotations

from videogen.plugins.captions.highlight_box.compile import compile_highlight_box
from videogen.plugins.captions.highlight_box.params import HighlightBoxParams
from videogen.plugins.captions.registry import CaptionStyleContract, register_caption_style

register_caption_style(
    "highlight-box",
    CaptionStyleContract(
        description=(
            "Neon highlighter boxes: each word wraps in its own colored box with a slight rotation "
            "jitter and a per-word spring pop. High-energy TikTok look for hooks and emphasis."
        ),
        params_model=HighlightBoxParams,
        defaults={},  # the schema's field defaults are the look; overrides may be layered on
        compile=compile_highlight_box,
    ),
)

__all__ = ["HighlightBoxParams", "compile_highlight_box"]
