"""Layout plugins: `full` and `split-h` (ADR 0001, CONTEXT.md).

A Layout is a backend-agnostic plugin: a contract declaring its named Region slots plus a pure
`to_ir` that places each filled Region's Reference as a `media` Layer with the geometry the preset
owns. These tests assert that observable behavior -- the region slots, the preset geometry for the
default 50/50 split and a custom `ratio`, and that an out-of-range `ratio` is rejected by the
contract (so a malformed frame is caught at authoring time, user story 31). No free-form rects ever
appear in a Scene; geometry lives in the preset.
"""

from __future__ import annotations

from videogen.kernel.composition import (
    Asset,
    AssetType,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)
from videogen.kernel.ir import Layer, MediaLayer
from videogen.kernel.registry import CompileContext, get_layout

_CTX = CompileContext(
    assets={
        "host": Asset(type=AssetType.video, src="host.mp4"),
        "broll": Asset(type=AssetType.image, src="tweet.png"),
    }
)


def _split_scene(*, ratio: float | None = None) -> Scene:
    params = {"ratio": ratio} if ratio is not None else {}
    return Scene(
        id="s0",
        start=0.0,
        end=4.0,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host"), RegionName.bottom: Ref(asset="broll")},
        layout_params=params,
    )


def _media_by_src(layers: list[Layer], src: str) -> MediaLayer:
    return next(layer for layer in layers if isinstance(layer, MediaLayer) and layer.src == src)


# --- full ---


def test_full_places_one_full_frame_media_layer() -> None:
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host")},
    )
    contract = get_layout(LayoutName.full)
    assert contract is not None
    layers = contract.to_ir(scene, _CTX)
    assert len(layers) == 1
    media = _media_by_src(layers, "host.mp4")
    assert media.rect is None  # full frame: no sub-rect
    assert media.content == "video"  # the host recording is a video asset
    assert (media.start, media.end) == (0.0, 2.0)


def test_full_frame_image_broll_carries_image_content() -> None:
    # Full-frame b-roll is a `full` Scene filled with an image Asset (a screenshot). The IR must
    # carry that it is an image so the backend paints it as a still, not as a video (CONTEXT.md).
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="broll")},
    )
    contract = get_layout(LayoutName.full)
    assert contract is not None
    media = _media_by_src(contract.to_ir(scene, _CTX), "tweet.png")
    assert media.content == "image"


# --- split-h geometry ---


def test_split_h_defaults_to_a_5050_split() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    layers = contract.to_ir(_split_scene(), _CTX)

    top = _media_by_src(layers, "host.mp4")
    bottom = _media_by_src(layers, "tweet.png")
    assert top.rect is not None and bottom.rect is not None
    # Top occupies the upper half, bottom the lower half, together tiling the frame.
    assert (top.rect.x, top.rect.y, top.rect.width, top.rect.height) == (0.0, 0.0, 1.0, 0.5)
    assert (bottom.rect.x, bottom.rect.y, bottom.rect.width, bottom.rect.height) == (
        0.0,
        0.5,
        1.0,
        0.5,
    )


def test_split_h_ratio_weights_the_top_region() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    layers = contract.to_ir(_split_scene(ratio=0.7), _CTX)

    top = _media_by_src(layers, "host.mp4")
    bottom = _media_by_src(layers, "tweet.png")
    assert top.rect is not None and bottom.rect is not None
    assert (top.rect.y, top.rect.height) == (0.0, 0.7)
    assert bottom.rect.y == 0.7
    assert abs(bottom.rect.height - 0.3) < 1e-9  # 1 - ratio, modulo float


def test_split_h_only_emits_layers_for_filled_regions() -> None:
    # A split-h scene that fills only `top` produces just one media layer.
    scene = Scene(
        id="s0",
        start=0.0,
        end=4.0,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="host")},
    )
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    layers = contract.to_ir(scene, _CTX)
    assert len(layers) == 1
    assert _media_by_src(layers, "host.mp4").rect is not None


# --- ratio validation (story 31) ---


def test_split_h_rejects_ratio_at_or_below_zero() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    assert contract.validate_params(_split_scene(ratio=0.0)) != []


def test_split_h_rejects_ratio_at_or_above_one() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    assert contract.validate_params(_split_scene(ratio=1.0)) != []


def test_split_h_accepts_an_in_range_ratio() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    assert contract.validate_params(_split_scene(ratio=0.6)) == []


def test_full_takes_no_params_and_validates_clean() -> None:
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host")},
    )
    contract = get_layout(LayoutName.full)
    assert contract is not None
    assert contract.validate_params(scene) == []


def test_reference_in_point_is_threaded_into_the_media_layer() -> None:
    # One long recording jump-cut across scenes: the Reference in-point reaches the IR (story 26).
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host", in_point=3.5)},
    )
    contract = get_layout(LayoutName.full)
    assert contract is not None
    media = _media_by_src(contract.to_ir(scene, _CTX), "host.mp4")
    assert media.in_point == 3.5
