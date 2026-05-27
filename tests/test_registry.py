"""Plugin registry + completeness contract test (ADR 0001, ADR 0002).

The registry is the single place `compile_ir` and the Validator look a Layout up, so the plugin set
is defined in exactly one location (user story 30). These tests assert the registry's observable
contract -- which Layouts it exposes, the Region slots each declares -- and the completeness check
that is the drift guard ADR 0002 relies on: every registered plugin compiles to IR, and every IR
layer kind the plugins can emit is one the backend interprets. A registered Layout whose `to_ir`
emits a kind the backend does not handle must be *caught by the check*, not discovered at render.
"""

from __future__ import annotations

from videogen.backends.remotion import RemotionBackend
from videogen.kernel.composition import (
    Asset,
    AssetType,
    InsertOverlay,
    LayoutName,
    Ref,
    RegionName,
    Scene,
    ZoomOverlay,
)
from videogen.kernel.ir import AudioLayer, Layer, MediaLayer, Transform
from videogen.kernel.registry import (
    CompileContext,
    LayoutContract,
    OverlayContract,
    OverlayFragment,
    OverlayKind,
    Registry,
    default_registry,
    get_layout,
    layout_regions,
)


def test_builtin_registry_exposes_full_and_split_h() -> None:
    names = default_registry().layout_names()
    assert LayoutName.full in names
    assert LayoutName.split_h in names


def test_full_layout_declares_only_the_full_region() -> None:
    assert layout_regions(LayoutName.full) == frozenset({RegionName.full})


def test_split_h_layout_declares_top_and_bottom_regions() -> None:
    assert layout_regions(LayoutName.split_h) == frozenset({RegionName.top, RegionName.bottom})


def test_get_layout_returns_a_contract_for_a_known_layout() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    assert contract.regions == frozenset({RegionName.top, RegionName.bottom})


# --- the completeness contract test (the drift guard) ---


def test_every_registered_layout_compiles_to_ir() -> None:
    # Every plugin in the registry must produce IR; a Layout missing a working `to_ir` is a build
    # failure, not a render-time surprise (user story 3).
    assert default_registry().emitted_layer_kinds()  # non-empty: at least the `media` kind


def test_registry_emits_only_kinds_the_backend_interprets() -> None:
    # Every IR layer kind the registered plugins can emit must be one the backend handles (story 4).
    violations = default_registry().completeness_violations(RemotionBackend.HANDLED_KINDS)
    assert violations == []


def test_completeness_check_catches_a_layout_emitting_an_unhandled_kind() -> None:
    # Drift: a Layout whose `to_ir` emits a kind the backend cannot render. The check must flag it
    # (this is what fails the build), rather than letting it reach the backend (ADR 0002).
    isolated = Registry()

    def bad_to_ir(scene: Scene, ctx: CompileContext) -> list[Layer]:
        return [AudioLayer(start=0.0, end=1.0, src="x.m4a")]

    isolated.register_layout(
        LayoutName.full,
        LayoutContract(regions=frozenset({RegionName.full}), to_ir=bad_to_ir),
    )
    handled = frozenset({"media"})  # a backend that only paints media
    assert isolated.completeness_violations(handled) != []


# --- overlay registry (Phase 6): the same single-source seam, now for effect overlays ---


def _additive(layers: tuple[Layer, ...]) -> OverlayContract:
    return OverlayContract(
        kind=OverlayKind.additive,
        to_ir=lambda overlay, ctx: OverlayFragment(layers=layers),
        probe=InsertOverlay(start=0.0, end=1.0, asset="a"),
    )


def _transform(transform: Transform | None) -> OverlayContract:
    return OverlayContract(
        kind=OverlayKind.transform,
        to_ir=lambda overlay, ctx: OverlayFragment(transform=transform),
        probe=ZoomOverlay(start=0.0, end=1.0),
    )


def test_register_and_get_an_overlay_contract() -> None:
    reg = Registry()
    contract = _transform(Transform())
    reg.register_overlay("zoom", contract)
    assert reg.get_overlay("zoom") is contract
    assert "zoom" in reg.overlay_types()


def test_overlay_contract_declares_its_transform_or_additive_kind() -> None:
    # The classification is stated by the plugin, not inferred from the type name (PRD decision).
    reg = Registry()
    reg.register_overlay("insert", _additive((MediaLayer(start=0.0, end=1.0, src="x"),)))
    contract = reg.get_overlay("insert")
    assert contract is not None and contract.kind is OverlayKind.additive


def test_overlay_completeness_catches_an_additive_emitting_an_unhandled_kind() -> None:
    reg = Registry()
    reg.register_overlay("insert", _additive((AudioLayer(start=0.0, end=1.0, src="x.m4a"),)))
    assert reg.overlay_completeness_violations(frozenset({"media"})) != []


def test_overlay_completeness_catches_a_transform_compiling_to_nothing() -> None:
    # A transform overlay must emit a transform fragment; one that compiles to nothing is drift.
    reg = Registry()
    reg.register_overlay("zoom", _transform(None))
    assert reg.overlay_completeness_violations(frozenset({"media"})) != []


def test_a_clean_overlay_set_has_no_completeness_violations() -> None:
    reg = Registry()
    reg.register_overlay("insert", _additive((MediaLayer(start=0.0, end=1.0, src="x"),)))
    reg.register_overlay("zoom", _transform(Transform()))
    assert reg.overlay_completeness_violations(frozenset({"media"})) == []


# --- layout region geometry, exposed for transform-overlay targeting (Phase 6) ---


def test_split_h_exposes_per_region_geometry_for_effect_targeting() -> None:
    contract = get_layout(LayoutName.split_h)
    assert contract is not None
    scene = Scene(
        id="s0",
        start=0.0,
        end=4.0,
        layout=LayoutName.split_h,
        regions={RegionName.top: Ref(asset="a"), RegionName.bottom: Ref(asset="a")},
        layout_params={"ratio": 0.7},
    )
    rects = contract.region_rects(scene)
    assert rects[RegionName.top].height == 0.7
    assert rects[RegionName.bottom].y == 0.7


def test_full_layout_exposes_no_sub_region_geometry() -> None:
    # `full` fills the whole frame, so it has no sub-region rect; a `full` target means the frame.
    contract = get_layout(LayoutName.full)
    assert contract is not None
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="a")},
    )
    assert contract.region_rects(scene) == {}


def test_a_layout_to_ir_can_be_invoked_through_its_contract() -> None:
    # The registry is the seam compile_ir drives: resolve a Layout, call its to_ir with a context.
    contract = get_layout(LayoutName.full)
    assert contract is not None
    scene = Scene(
        id="s0",
        start=0.0,
        end=2.0,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="a")},
    )
    ctx = CompileContext(assets={"a": Asset(type=AssetType.video, src="host.mp4")})
    layers = contract.to_ir(scene, ctx)
    assert [layer.kind for layer in layers] == ["media"]
    media = layers[0]
    assert isinstance(media, MediaLayer)
    assert media.src == "host.mp4"
    assert media.rect is None  # full frame
