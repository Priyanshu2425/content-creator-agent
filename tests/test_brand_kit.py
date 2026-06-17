"""BrandKit builder (restructure/02): the Director's locked design-language token spec.

These tests pin the pure behavior of the builder — given a brief and an optional brand profile it
returns a locked kit — and the StyleBrief projection that feeds the stat-viz renderer. No LLM, no
render: the token assembly is deterministic and verifiable in isolation.
"""

from __future__ import annotations

import pytest

from videogen.agent.brand_kit import (
    CAPTION_STYLES,
    BrandKit,
    FrameMeta,
    build_brand_kit,
)
from videogen.agent.stat_viz import StyleBrief


def test_default_kit_has_all_v1_tokens_when_no_profile_supplied() -> None:
    kit = build_brand_kit(brief="a punchy fitness explainer")

    assert set(kit.colors) >= {"bg", "primary", "accent"}
    assert kit.font
    assert kit.caption_style in CAPTION_STYLES
    assert kit.safe_zones.top_pct > 0 and kit.safe_zones.bottom_pct > 0
    assert set(kit.sfx_palette) == {"click", "whoosh", "dramatic_whoosh"}
    assert kit.sfx_budget.max_per_10s >= 1 and kit.sfx_budget.min_gap_ms > 0


def test_profile_is_loaded_and_locked() -> None:
    profile = {
        "colors": {"bg": "#101820", "primary": "#F2F2F2", "accent": "#00B4D8"},
        "font": "Poppins, sans-serif",
        "caption_style": "kinetic",
    }
    kit = build_brand_kit(brief="anything", profile=profile)

    assert kit.colors["bg"] == "#101820"
    assert kit.colors["accent"] == "#00B4D8"
    assert kit.font == "Poppins, sans-serif"
    assert kit.caption_style == "kinetic"


def test_unknown_caption_style_in_profile_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_brand_kit(brief="x", profile={"caption_style": "neon-blast"})


def test_partial_profile_fills_the_rest_from_defaults() -> None:
    kit = build_brand_kit(brief="x", profile={"colors": {"accent": "#FF0000"}})

    assert kit.colors["accent"] == "#FF0000"
    # untouched tokens fall back to sensible defaults
    assert kit.colors["bg"]
    assert kit.font
    assert kit.caption_style in CAPTION_STYLES


def test_frame_meta_is_carried_and_aspect_derived() -> None:
    kit = build_brand_kit(brief="x", frame=FrameMeta.of(width=1080, height=1920, fps=30))

    assert kit.frame is not None
    assert kit.frame.width == 1080 and kit.frame.height == 1920 and kit.frame.fps == 30
    assert kit.frame.aspect == "9:16"


def test_kit_with_no_frame_meta_is_allowed() -> None:
    # The Director can build the style tokens before the host is probed; frame meta fills in later.
    kit = build_brand_kit(brief="x")
    assert kit.frame is None


def test_to_style_brief_projects_colors_and_font() -> None:
    kit = build_brand_kit(
        brief="x",
        profile={
            "colors": {"bg": "#111111", "primary": "#EEEEEE", "accent": "#FF6B35"},
            "font": "Inter, sans-serif",
        },
    )
    style = kit.to_style_brief()

    assert isinstance(style, StyleBrief)
    assert style.background == "#111111"
    assert style.primary == "#EEEEEE"
    assert style.accent == "#FF6B35"
    assert style.font_family == "Inter, sans-serif"


def test_tokens_are_compact_and_json_safe() -> None:
    # Workers receive the kit as compact tokens (not prose); it must be a plain JSON-able dict.
    import json

    kit = build_brand_kit(brief="x", frame=FrameMeta.of(width=1080, height=1920, fps=30))
    tokens = kit.tokens()

    assert isinstance(tokens, dict)
    json.dumps(tokens)  # must not raise
    assert tokens["caption_style"] in CAPTION_STYLES
    assert "sfx_palette" in tokens and "safe_zones" in tokens


def test_default_kit_is_immutable() -> None:
    kit = build_brand_kit(brief="x")
    with pytest.raises((AttributeError, TypeError)):
        kit.font = "Comic Sans"  # type: ignore[misc]
