"""Caption style registry: get / list / compile, unknown-id handling, built-in IR (ADR 0010).

Mirrors the former ``plugins/captions`` style tests against the new registry. The three built-ins
(``pill``/``word-bold``/``kinetic``) are the same generic karaoke renderer configured by different
params; these tests pin that each compiles to the exact IR the old ``compile_caption_style`` did, so
the migration is behavior-preserving. The unknown-id rule -- error by default, skip-with-warning
under ``strict: False`` -- is checked at both the registry seam and through ``compile_ir``.
"""

from __future__ import annotations

import logging

import pytest

from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Caption,
    Composition,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)
from videogen.kernel.ir import TextLayer
from videogen.plugins.captions.registry import (
    UnknownCaptionStyleError,
    default_caption_registry,
)


def _registry():  # type: ignore[no-untyped-def]
    return default_caption_registry()


# --- get / list / has / ids ---


def test_get_returns_a_contract_for_each_builtin() -> None:
    r = _registry()
    for style_id in ("pill", "word-bold", "kinetic"):
        contract = r.get(style_id)
        assert contract is not None
        assert contract.description  # a non-empty human description for discovery


def test_get_unknown_id_returns_none() -> None:
    assert _registry().get("does-not-exist") is None


def test_ids_are_the_builtins_including_highlight_box_and_tiktok() -> None:
    assert _registry().ids() == frozenset(
        {"pill", "word-bold", "kinetic", "highlight-box", "tiktok"}
    )


def test_list_returns_id_description_pairs_sorted() -> None:
    listed = _registry().list()
    assert [style_id for style_id, _ in listed] == [
        "highlight-box",
        "kinetic",
        "pill",
        "tiktok",
        "word-bold",
    ]
    assert all(isinstance(desc, str) and desc for _, desc in listed)


# --- compile: each built-in's IR pieces (behavior preservation) ---


def test_pill_is_constant_within_its_span() -> None:
    compiled = _registry().compile("pill", 0.0, 1.0)
    assert [(k.t, k.value) for k in compiled.opacity.keyframes] == [(0.0, 1.0)]
    assert compiled.transform is None
    assert compiled.emphasis is False
    assert compiled.props.font_size == 64
    assert compiled.props.background == "rgba(17,24,39,0.85)"
    assert compiled.props.highlight_color == "#FFE14D"


def test_word_bold_is_constant_and_emphasized_with_no_pill() -> None:
    compiled = _registry().compile("word-bold", 0.0, 1.0)
    assert compiled.transform is None
    assert compiled.emphasis is True
    assert compiled.props.background is None
    assert compiled.props.font_size == 76


def test_kinetic_pops_in_via_opacity_and_scale_tracks() -> None:
    compiled = _registry().compile("kinetic", 0.0, 2.0)
    opacity = compiled.opacity.keyframes
    assert opacity[0].t == 0.0 and opacity[0].value == 0.0
    assert opacity[1].value == 1.0 and 0.0 < opacity[1].t <= 2.0
    assert compiled.transform is not None and compiled.transform.scale is not None
    scale = compiled.transform.scale.keyframes
    assert scale[0].t == 0.0 and 0.0 < scale[0].value < 1.0
    assert scale[1].value == 1.0
    assert compiled.emphasis is True
    assert compiled.props.font_size == 120


def test_kinetic_pop_window_is_clamped_to_half_the_span() -> None:
    # A caption shorter than twice the pop window settles by mid-span, not at the fixed 0.18s.
    compiled = _registry().compile("kinetic", 0.0, 0.2)
    settle = compiled.opacity.keyframes[1].t
    assert settle == pytest.approx(0.1)  # half of the 0.2s span


# --- highlight-box: the first net-new renderer's IR pieces (defaults + overrides) ---


def test_highlight_box_compiles_defaults_to_its_own_param_schema() -> None:
    from videogen.kernel.ir import HighlightBoxStyle

    compiled = _registry().compile("highlight-box", 0.0, 2.0)
    # No layer-level animation tracks: the per-word pop is owned by the TS component.
    assert [(k.t, k.value) for k in compiled.opacity.keyframes] == [(0.0, 1.0)]
    assert compiled.transform is None
    assert compiled.emphasis is False
    # Its props are the highlight-box schema, not the generic TextStyle.
    assert isinstance(compiled.props, HighlightBoxStyle)
    assert compiled.props.text_color == "#0B0B0B"
    assert len(compiled.props.box_colors) >= 1
    assert compiled.props.rotation_jitter_deg > 0.0
    assert compiled.props.pop_seconds > 0.0


def test_highlight_box_compile_applies_param_overrides() -> None:
    compiled = _registry().compile(
        "highlight-box",
        0.0,
        2.0,
        params={"box_colors": ["#FF0000"], "rotation_jitter_deg": 0.0, "font_size": 100},
    )
    assert compiled.props.box_colors == ["#FF0000"]
    assert compiled.props.rotation_jitter_deg == 0.0
    assert compiled.props.font_size == 100


# --- tiktok: the Remotion-template port's IR pieces (defaults + overrides) ---


def test_tiktok_compiles_defaults_to_its_own_param_schema() -> None:
    from videogen.kernel.ir import TikTokStyle

    compiled = _registry().compile("tiktok", 0.0, 2.0)
    # No layer-level animation tracks: the enter spring + active highlight are owned by the component.
    assert [(k.t, k.value) for k in compiled.opacity.keyframes] == [(0.0, 1.0)]
    assert compiled.transform is None
    assert compiled.emphasis is False
    # Its props are the tiktok schema, not the generic TextStyle.
    assert isinstance(compiled.props, TikTokStyle)
    assert compiled.props.active_color == "#39E508"  # the template's TikTok green
    assert compiled.props.stroke_width > 0
    assert compiled.props.pop_seconds > 0.0


def test_tiktok_compile_applies_param_overrides() -> None:
    compiled = _registry().compile(
        "tiktok",
        0.0,
        2.0,
        params={"active_color": "#FF0000", "stroke_width": 0, "font_size": 96},
    )
    assert compiled.props.active_color == "#FF0000"
    assert compiled.props.stroke_width == 0
    assert compiled.props.font_size == 96


# --- unknown-id rule: error by default, skip-with-warning under strict: False ---


def test_compile_unknown_id_raises() -> None:
    with pytest.raises(UnknownCaptionStyleError):
        _registry().compile("nope", 0.0, 1.0)


def _comp_with_unknown_style(*, strict: bool) -> Composition:
    # Bypass the Caption field validator (which rejects an unknown id at construction) so we can
    # test the compile-time strict downgrade in isolation -- a newer doc on an older render.
    caption = Caption.model_construct(text="x", start=0.1, end=0.5, style="nope", z=100, words=())
    return Composition(
        strict=strict,
        assets={"h": Asset(type=AssetType.video, src="h.mp4")},
        voiceover=Audio(asset="h"),
        scenes=[
            Scene(
                id="s",
                start=0.0,
                end=1.0,
                layout=LayoutName.full,
                regions={RegionName.full: Ref(asset="h")},
            )
        ],
        captions=[caption],
    )


def test_compile_ir_raises_on_unknown_style_by_default() -> None:
    with pytest.raises(UnknownCaptionStyleError):
        compile_ir(_comp_with_unknown_style(strict=True), fps=30, duration=1.0)


def test_compile_ir_skips_unknown_style_with_warning_under_strict_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        ir = compile_ir(_comp_with_unknown_style(strict=False), fps=30, duration=1.0)
    assert not [layer for layer in ir.layers if isinstance(layer, TextLayer)]  # skipped
    assert any("unknown style" in record.message for record in caplog.records)


# --- the Caption field validator: open registry key, not a closed enum ---


def test_caption_accepts_each_registered_id() -> None:
    for style_id in ("pill", "word-bold", "kinetic"):
        assert Caption(text="x", start=0.0, end=1.0, style=style_id).style == style_id


def test_caption_rejects_an_unknown_id() -> None:
    with pytest.raises(ValueError):
        Caption(text="x", start=0.0, end=1.0, style="bold")
