"""Overlay plugins: `zoom`, `pan`, `insert` (Phase 6, ADR 0001/0002).

These tests assert each plugin's observable contract -- the neutral IR fragment its `to_ir` emits
and the params its registry contract rejects -- never the plugin's internals. The load-bearing
distinction (CONTEXT.md, ADR 0001): a transform overlay (`zoom`/`pan`) emits a transform fragment
and *no* painted layer, while an additive overlay (`insert`) emits exactly one painted media layer
and no transform. The built-ins are reached through the same registry seam `compile_ir` drives, so
the tests resolve them via `get_overlay` rather than importing the plugin modules directly.
"""

from __future__ import annotations

from videogen.backends.remotion import RemotionBackend
from videogen.kernel.composition import (
    Anchor,
    Asset,
    AssetType,
    InsertOverlay,
    PanOverlay,
    ZoomOverlay,
)
from videogen.kernel.ir import MediaLayer
from videogen.kernel.registry import (
    CompileContext,
    OverlayContract,
    OverlayKind,
    default_registry,
    get_overlay,
)

_CTX = CompileContext(
    assets={"card": Asset(type=AssetType.image, src="tweet.png")},
    width=1080,
    height=1920,
)


def _overlay(type_name: str) -> OverlayContract:
    contract = get_overlay(type_name)
    assert contract is not None, f"overlay '{type_name}' is not registered"
    return contract


# --- zoom: a transform overlay (scale track, no painted layer) ---


def test_zoom_emits_a_scale_transform_and_no_painted_layer() -> None:
    fragment = _overlay("zoom").to_ir(
        ZoomOverlay(start=1.0, end=3.0, from_scale=1.0, to_scale=1.5), _CTX
    )
    assert fragment.layers == ()  # transform overlays paint nothing (CONTEXT.md)
    assert fragment.transform is not None and fragment.transform.scale is not None
    keyframes = fragment.transform.scale.keyframes
    assert (keyframes[0].t, keyframes[0].value) == (1.0, 1.0)
    assert (keyframes[-1].t, keyframes[-1].value) == (3.0, 1.5)


def test_zoom_declares_the_transform_kind() -> None:
    assert _overlay("zoom").kind is OverlayKind.transform


# --- pan: a transform overlay (translate track in pixels, no painted layer) ---


def test_pan_emits_a_translate_transform_in_pixels() -> None:
    fragment = _overlay("pan").to_ir(PanOverlay(start=0.0, end=2.0, dx=0.1, dy=0.0), _CTX)
    assert fragment.layers == ()
    assert fragment.transform is not None and fragment.transform.translate_x is not None
    assert fragment.transform.translate_x.keyframes[-1].value == 0.1 * 1080  # fraction -> pixels
    assert fragment.transform.translate_y is None  # no vertical motion -> no track


def test_pan_declares_the_transform_kind() -> None:
    assert _overlay("pan").kind is OverlayKind.transform


# --- insert: an additive overlay (one painted media layer, placed by anchor/scale) ---


def test_insert_emits_one_painted_media_layer_placed_by_anchor() -> None:
    fragment = _overlay("insert").to_ir(
        InsertOverlay(start=2.0, end=4.0, z=60, asset="card", anchor=Anchor.top_right, scale=0.3),
        _CTX,
    )
    assert fragment.transform is None  # additive overlays carry no transform fragment
    assert len(fragment.layers) == 1
    layer = fragment.layers[0]
    assert isinstance(layer, MediaLayer)
    assert layer.src == "tweet.png" and layer.content == "image"  # image asset -> still
    assert (layer.start, layer.end, layer.z) == (2.0, 4.0, 60)  # z places it in the paint stack
    assert layer.rect is not None
    assert layer.rect.x > 0.5 and layer.rect.y < 0.1  # top-right: hugs the right and top edges


def test_insert_declares_the_additive_kind() -> None:
    assert _overlay("insert").kind is OverlayKind.additive


def test_insert_card_is_square_in_pixels() -> None:
    layer = (
        _overlay("insert")
        .to_ir(InsertOverlay(start=0.0, end=1.0, asset="card", scale=0.3), _CTX)
        .layers[0]
    )
    assert isinstance(layer, MediaLayer) and layer.rect is not None
    # width fraction * canvas width == height fraction * canvas height: a square box on 9:16.
    assert abs(layer.rect.width * 1080 - layer.rect.height * 1920) < 1e-6


def test_insert_without_fade_is_constant_opacity() -> None:
    layer = (
        _overlay("insert").to_ir(InsertOverlay(start=0.0, end=4.0, asset="card"), _CTX).layers[0]
    )
    assert len(layer.opacity.keyframes) == 1  # constant: no ramp


def test_insert_fade_emits_an_opacity_ramp_in_and_out() -> None:
    layer = (
        _overlay("insert")
        .to_ir(InsertOverlay(start=0.0, end=4.0, asset="card", fade=0.5), _CTX)
        .layers[0]
    )
    keyframes = layer.opacity.keyframes
    assert len(keyframes) >= 3  # ramp in, hold, ramp out
    assert keyframes[0].value == 0.0 and keyframes[-1].value == 0.0  # fades from and to invisible


def test_insert_threads_the_source_in_point() -> None:
    layer = (
        _overlay("insert")
        .to_ir(InsertOverlay(start=0.0, end=1.0, asset="card", in_point=3.0), _CTX)
        .layers[0]
    )
    assert isinstance(layer, MediaLayer) and layer.in_point == 3.0


# --- the registry-owned param validation (the type-specific half of two-phase, story 9) ---


def test_zoom_rejects_a_non_positive_scale() -> None:
    assert _overlay("zoom").validate_params(ZoomOverlay(start=0.0, end=1.0, from_scale=0.0)) != []


def test_pan_rejects_an_out_of_range_offset() -> None:
    assert _overlay("pan").validate_params(PanOverlay(start=0.0, end=1.0, dx=1.5)) != []


def test_insert_rejects_a_scale_outside_zero_one() -> None:
    contract = _overlay("insert")
    assert (
        contract.validate_params(InsertOverlay(start=0.0, end=1.0, asset="card", scale=0.0)) != []
    )
    assert (
        contract.validate_params(InsertOverlay(start=0.0, end=1.0, asset="card", scale=1.5)) != []
    )


def test_in_range_params_validate_clean() -> None:
    assert _overlay("zoom").validate_params(ZoomOverlay(start=0.0, end=1.0)) == []
    assert _overlay("pan").validate_params(PanOverlay(start=0.0, end=1.0)) == []
    assert _overlay("insert").validate_params(InsertOverlay(start=0.0, end=1.0, asset="card")) == []


# --- registered + complete (the drift guard now covers the three effects, story 30) ---


def test_the_three_effects_are_registered_in_the_default_registry() -> None:
    assert {"zoom", "pan", "insert"} <= default_registry().overlay_types()


def test_the_three_effects_pass_the_completeness_check() -> None:
    violations = default_registry().overlay_completeness_violations(RemotionBackend.HANDLED_KINDS)
    assert violations == []
