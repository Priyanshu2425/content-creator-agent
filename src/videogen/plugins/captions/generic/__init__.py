"""The ``generic`` caption renderer + the three built-in styles it configures (ADR 0010).

``pill``, ``word-bold`` and ``kinetic`` are the original generic karaoke look -- now three registry
entries that are the *same* renderer (the same param schema + compile) with different defaults. The
defaults reproduce the former ``_PROPS``/``_EMPHASIS`` dicts and the kinetic pop constants exactly,
so the migrated styles render identically (ADR 0010's behavior-preservation requirement).

Importing this package registers the three styles into the default caption registry (the import side
effect ``default_caption_registry`` triggers lazily), exactly as the Layout/overlay plugins do.
"""

from __future__ import annotations

from videogen.plugins.captions.generic.compile import compile_generic
from videogen.plugins.captions.generic.params import GenericCaptionParams
from videogen.plugins.captions.registry import CaptionStyleContract, register_caption_style

# kinetic pop-in: opacity 0->1 and scale 0.6->1 over 0.18s, eased to a settle (former constants).
_KINETIC_POP_SECONDS = 0.18
_KINETIC_START_SCALE = 0.6

# The shared accent the active karaoke word pops to (was the same across all three styles).
_ACCENT = "#FFE14D"

# Each entry is the generic renderer with this style id's param defaults (former _PROPS/_EMPHASIS).
_BUILTINS: dict[str, tuple[str, dict[str, object]]] = {
    "pill": (
        "Dark rounded pill behind centered text; the spoken word pops accent (normal narration).",
        {
            "font_size": 64,
            "font_weight": 700,
            "color": "#FFFFFF",
            "background": "rgba(17,24,39,0.85)",
            "border_radius": 24,
            "padding_x": 40,
            "padding_y": 18,
            "highlight_color": _ACCENT,
            "emphasis": False,
        },
    ),
    "word-bold": (
        "Plain bold white line, no pill; the active word pops accent, one key word emphasized.",
        {
            "font_size": 76,
            "font_weight": 800,
            "color": "#FFFFFF",
            "highlight_color": _ACCENT,
            "emphasis": True,
        },
    ),
    "kinetic": (
        "Large bold line that pops in (opacity + scale spring); the active word pops accent.",
        {
            "font_size": 120,
            "font_weight": 900,
            "color": "#FFFFFF",
            "highlight_color": _ACCENT,
            "emphasis": True,
            "pop_seconds": _KINETIC_POP_SECONDS,
            "pop_start_scale": _KINETIC_START_SCALE,
        },
    ),
}

for _style_id, (_description, _defaults) in _BUILTINS.items():
    register_caption_style(
        _style_id,
        CaptionStyleContract(
            description=_description,
            params_model=GenericCaptionParams,
            defaults=_defaults,
            compile=compile_generic,
        ),
    )

__all__ = ["GenericCaptionParams", "compile_generic"]
