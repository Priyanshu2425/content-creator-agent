"""BrandKit: the Director's locked, per-video design-language token spec (restructure/02, ADR 0008).

The Director owns the brand kit and injects it to every worker as compact tokens — the single source
of truth for the video's look. It is built once per video from an optional **brand profile** (a
user-supplied dict) or, when none is given, derived as sensible defaults from the brief, then locked
(frozen) for the whole run.

v1 tokens: colors (bg/primary/accent), font, caption style (one of the fixed kernel set), sfx palette
+ density budget (carried for the SFXAgent), frame meta, and safe zones. Motion/graphics/logo/sound
tokens grow in later phases.

`StyleBrief` (the stat-viz renderer's style contract) is produced as a *projection* of the brand kit
via `to_style_brief()`, so `DEFAULT_STYLE_BRIEF` stops being the source of truth — the pipeline always
injects the kit's projection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import gcd
from typing import Any

from videogen.agent.stat_viz import StyleBrief
from videogen.plugins.captions.registry import caption_style_ids, is_registered_caption_style


def _registered_caption_styles() -> tuple[str, ...]:
    """The caption-style ids the kernel knows -- now the open caption registry, not a closed enum.

    Adding a renderer (e.g. ``highlight-box``) makes it a valid brand-kit default automatically, with
    no change here (ADR 0010). Sorted for a stable error message / token view.
    """
    return tuple(sorted(caption_style_ids()))


# Back-compat alias: callers/tests that imported the closed set get the registered ids instead.
CAPTION_STYLES: tuple[str, ...] = _registered_caption_styles()

# v1 sound kit: the three real assets that exist under the Remotion project's public/assets/sfx.
_DEFAULT_SFX_PALETTE: dict[str, str] = {
    "click": "assets/sfx/click.mp3",
    "whoosh": "assets/sfx/whoosh.mp3",
    "dramatic_whoosh": "assets/sfx/dramatic_whoosh.mp3",
}

_DEFAULT_COLORS: dict[str, str] = {"bg": "#0D0D0D", "primary": "#FFFFFF", "accent": "#FF6B35"}
_DEFAULT_FONT = "Inter, Arial, sans-serif"
_DEFAULT_CAPTION_STYLE = "tiktok"


@dataclass(frozen=True)
class FrameMeta:
    """Frame geometry tokens (from the host probe). Aspect is derived, not authored."""

    width: int
    height: int
    fps: int
    aspect: str

    @classmethod
    def of(cls, *, width: int, height: int, fps: int) -> "FrameMeta":
        return cls(width=width, height=height, fps=fps, aspect=_aspect(width, height))


@dataclass(frozen=True)
class SafeZones:
    """Fractions of the frame the Director keeps overlays/captions clear of (behavioral in v1)."""

    top_pct: float = 12.0
    bottom_pct: float = 22.0


@dataclass(frozen=True)
class SfxBudget:
    """Density limits for the SFXAgent (carried on the kit; enforced by the worker in Phase 3)."""

    min_gap_ms: int = 2500
    max_per_10s: int = 3
    no_overlap: bool = True


@dataclass(frozen=True)
class BrandKit:
    """The locked design-language token spec. Frozen: once built it cannot drift."""

    colors: dict[str, str]
    font: str
    caption_style: str
    safe_zones: SafeZones
    sfx_palette: dict[str, str]
    sfx_budget: SfxBudget
    frame: FrameMeta | None = None

    def to_style_brief(self) -> StyleBrief:
        """Project the kit onto the stat-viz renderer's style contract."""
        return StyleBrief(
            background=self.colors["bg"],
            primary=self.colors["primary"],
            accent=self.colors["accent"],
            font_family=self.font,
        )

    def tokens(self) -> dict[str, Any]:
        """The compact, JSON-safe token view injected to workers (never prose)."""
        out: dict[str, Any] = {
            "colors": dict(self.colors),
            "font": self.font,
            "caption_style": self.caption_style,
            "safe_zones": {"top_pct": self.safe_zones.top_pct, "bottom_pct": self.safe_zones.bottom_pct},
            "sfx_palette": dict(self.sfx_palette),
            "sfx_budget": {
                "min_gap_ms": self.sfx_budget.min_gap_ms,
                "max_per_10s": self.sfx_budget.max_per_10s,
                "no_overlap": self.sfx_budget.no_overlap,
            },
        }
        if self.frame is not None:
            out["frame"] = {
                "width": self.frame.width,
                "height": self.frame.height,
                "fps": self.frame.fps,
                "aspect": self.frame.aspect,
            }
        return out

    def with_frame(self, frame: FrameMeta) -> "BrandKit":
        """Return a copy with frame meta filled in (used once the host is probed)."""
        return replace(self, frame=frame)


def build_brand_kit(
    *,
    brief: str = "",
    profile: dict[str, Any] | None = None,
    frame: FrameMeta | None = None,
) -> BrandKit:
    """Build and lock the brand kit.

    With a `profile`, load its tokens over the defaults (partial profiles are allowed; missing tokens
    fall back). With none, derive a sensible default kit. The `brief` is reserved for future
    LLM-assisted derivation; v1 derivation is deterministic so the builder is unit-testable.
    """
    profile = profile or {}

    colors = {**_DEFAULT_COLORS, **_coerce_colors(profile.get("colors"))}
    font = profile.get("font") or _DEFAULT_FONT
    caption_style = profile.get("caption_style") or _DEFAULT_CAPTION_STYLE
    if not is_registered_caption_style(caption_style):
        raise ValueError(
            f"unknown caption_style {caption_style!r}; "
            f"must be a registered caption style: {_registered_caption_styles()}"
        )

    safe_zones = _coerce_safe_zones(profile.get("safe_zones"))
    sfx_palette = {**_DEFAULT_SFX_PALETTE, **_coerce_str_map(profile.get("sfx_palette"))}
    sfx_budget = _coerce_sfx_budget(profile.get("sfx_budget"))

    return BrandKit(
        colors=colors,
        font=font,
        caption_style=caption_style,
        safe_zones=safe_zones,
        sfx_palette=sfx_palette,
        sfx_budget=sfx_budget,
        frame=frame,
    )


def _aspect(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unknown"
    g = gcd(width, height)
    return f"{width // g}:{height // g}"


def _coerce_colors(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def _coerce_str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _coerce_safe_zones(raw: Any) -> SafeZones:
    if not isinstance(raw, dict):
        return SafeZones()
    return SafeZones(
        top_pct=float(raw.get("top_pct", SafeZones().top_pct)),
        bottom_pct=float(raw.get("bottom_pct", SafeZones().bottom_pct)),
    )


def _coerce_sfx_budget(raw: Any) -> SfxBudget:
    if not isinstance(raw, dict):
        return SfxBudget()
    d = SfxBudget()
    return SfxBudget(
        min_gap_ms=int(raw.get("min_gap_ms", d.min_gap_ms)),
        max_per_10s=int(raw.get("max_per_10s", d.max_per_10s)),
        no_overlap=bool(raw.get("no_overlap", d.no_overlap)),
    )
