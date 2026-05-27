"""Plugin registry + completeness check (ADR 0001, ADR 0002).

The registry is the single place the kernel looks a plugin up: `compile_ir` resolves a Scene's
Layout here to call its `to_ir`, and the Validator consults it for the Region slots a Layout
exposes and for Layout-parameter validity. Because the plugin set lives in exactly one location,
the completeness check and `compile_ir` agree on it by construction (user story 30). Adding a Layout
(and, in later phases, an overlay type or caption style) is a registry entry plus a pure `to_ir` --
never a change to `compile_ir`, the Composition schema, or a backend.

A **LayoutContract** is backend-agnostic: it declares the named Region slots the Layout exposes, a
pure `to_ir(scene, ctx) -> [Layer]` that places each filled Region's Reference as a `media` Layer
with the geometry the preset owns (ADR 0001 -- no free-form rects in a Scene), and an optional
`validate_params` that rejects out-of-range preset parameters at authoring time.

The **completeness check** is the drift guard ADR 0002 relies on: every registered plugin must
compile to IR, and every IR layer kind the plugins can emit must be one the backend interprets. It
is run as a contract test (see tests/test_registry.py) that fails the build on drift, rather than a
runtime branch.

This module is pure kernel and imports no backend. The built-in Layouts live under
``videogen/plugins/layouts/`` and register themselves into the default registry; the default
registry imports that package lazily on first use, so there is no import cycle between the kernel
registry and the plugins that populate it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from videogen.kernel.composition import (
    Asset,
    AssetId,
    AssetType,
    LayoutName,
    Overlay,
    Ref,
    RegionName,
    Scene,
)
from videogen.kernel.ir import Layer, Rect, Transform


@dataclass(frozen=True)
class CompileContext:
    """The facts a plugin's ``to_ir`` needs beyond the entity itself: the Asset library to resolve a
    Reference's id to a concrete media ``src``, plus the IR canvas size.

    Layout geometry is normalized and ignores the canvas size, but an effect overlay needs it: an
    ``insert``'s square card and a ``pan``'s pixel translate are derived from ``width``/``height``.
    Threaded by ``compile_ir`` when it drives each plugin."""

    assets: Mapping[AssetId, Asset]
    width: int = 1080
    height: int = 1920


def media_content(asset: Asset) -> Literal["video", "image"]:
    """Map an Asset to how a `media` Layer paints it: an image Asset is a still, else a clip.

    Layouts share this so the IR carries video-vs-image neutrally and the backend never inspects an
    Asset (ADR 0002). An ``audio`` Asset never reaches a Region, so it is treated as a clip here.
    """
    return "image" if asset.type is AssetType.image else "video"


def _no_param_errors(scene: Scene) -> list[str]:
    """Default param validation: a Layout with no preset parameters is always clean."""
    return []


def _no_region_rects(scene: Scene) -> dict[RegionName, Rect]:
    """Default region geometry: a whole-frame Layout exposes no addressable sub-region rect."""
    return {}


@dataclass(frozen=True)
class LayoutContract:
    """A Layout plugin: its Region slots, its pure ``to_ir``, its parameter validation, and the
    geometry of each Region (for effect targeting).

    ``regions`` is the set of named slots a Scene may fill (the Validator's source of truth for
    region validity). ``to_ir`` places each *filled* Region as a ``media`` Layer with the preset's
    geometry. ``validate_params`` reports messages for out-of-range ``layout_params`` (story 31).
    ``region_rects`` exposes the normalized destination rect of each named sub-Region for a Scene,
    so a transform overlay targeting ``top``/``bottom`` can be bound to that region's base content
    (Phase 6); a whole-frame Layout returns ``{}`` and a ``full`` target means the frame.
    """

    regions: frozenset[RegionName]
    to_ir: Callable[[Scene, CompileContext], list[Layer]]
    validate_params: Callable[[Scene], list[str]] = _no_param_errors
    region_rects: Callable[[Scene], dict[RegionName, Rect]] = _no_region_rects


# --- overlay plugins: the transform/additive split, behind the same registry seam (Phase 6) ---


class OverlayKind(StrEnum):
    """Declared classification driving compile-time routing (CONTEXT.md, ADR 0001).

    A ``transform`` overlay reshapes its target base region and paints nothing; an ``additive``
    overlay paints a new layer into the z-ordered paint stack. The plugin states this explicitly so
    ``compile_ir`` never infers it from the type name.
    """

    transform = "transform"
    additive = "additive"


@dataclass(frozen=True)
class OverlayFragment:
    """What an overlay's ``to_ir`` emits, in the neutral IR vocabulary (ADR 0002).

    A ``transform`` overlay returns a ``transform`` (keyframe tracks the compiler binds onto the
    target region's existing base content -- *no* new layer). An ``additive`` overlay returns
    ``layers`` (the painted media it contributes to the paint stack). The two are disjoint by kind.
    """

    transform: Transform | None = None
    layers: tuple[Layer, ...] = ()


def _no_overlay_param_errors(overlay: Overlay) -> list[str]:
    """Default overlay param validation: an overlay with no extra constraints is always clean."""
    return []


@dataclass(frozen=True)
class OverlayContract:
    """An overlay plugin: its declared kind, its pure ``to_ir``, and its parameter validation.

    ``probe`` is a representative instance used only by the completeness check to exercise ``to_ir``
    (never rendered), mirroring the synthetic Scene used for Layouts.
    """

    kind: OverlayKind
    to_ir: Callable[[Overlay, CompileContext], OverlayFragment]
    probe: Overlay
    validate_params: Callable[[Overlay], list[str]] = _no_overlay_param_errors


class Registry:
    """A mutable map of Layout name -> contract, with the completeness check over its contents."""

    def __init__(self) -> None:
        self._layouts: dict[LayoutName, LayoutContract] = {}
        self._overlays: dict[str, OverlayContract] = {}

    def register_layout(self, name: LayoutName, contract: LayoutContract) -> None:
        """Register (or replace) a Layout preset. Purely additive: no schema change (ADR 0001)."""
        self._layouts[name] = contract

    # --- overlays ---

    def register_overlay(self, type_name: str, contract: OverlayContract) -> None:
        """Register (or replace) an overlay type. Adding an action = a registry entry (ADR 0001)."""
        self._overlays[type_name] = contract

    def get_overlay(self, type_name: str) -> OverlayContract | None:
        return self._overlays.get(type_name)

    def overlay_types(self) -> frozenset[str]:
        return frozenset(self._overlays)

    def get_layout(self, name: LayoutName) -> LayoutContract | None:
        return self._layouts.get(name)

    def layout_names(self) -> frozenset[LayoutName]:
        return frozenset(self._layouts)

    def layout_regions(self, name: LayoutName) -> frozenset[RegionName]:
        """The Region slots ``name`` exposes, or empty if the Layout is unregistered."""
        contract = self._layouts.get(name)
        return contract.regions if contract is not None else frozenset()

    # --- completeness check (the drift guard, ADR 0002) ---

    def emitted_layer_kinds(self) -> set[str]:
        """Every IR layer kind the registered Layouts can emit.

        Each contract's ``to_ir`` is run on a synthetic Scene that fills all its Region slots, so
        the check observes the kinds a Layout actually produces rather than trusting a declaration.
        """
        kinds: set[str] = set()
        for name, contract in self._layouts.items():
            for layer in contract.to_ir(_probe_scene(name, contract), _PROBE_CTX):
                kinds.add(layer.kind)
        return kinds

    def completeness_violations(self, handled_kinds: frozenset[str]) -> list[str]:
        """Report every way the registry has drifted from what ``handled_kinds`` can render.

        Two invariants (user stories 3 and 4): every registered Layout compiles to *some* IR, and
        every kind any Layout emits is one the backend interprets. A non-empty result fails the
        build.
        """
        violations: list[str] = []
        for name, contract in self._layouts.items():
            produced = {
                layer.kind for layer in contract.to_ir(_probe_scene(name, contract), _PROBE_CTX)
            }
            if not produced:
                violations.append(f"layout '{name.value}' compiles to no IR layers")
            for kind in sorted(produced - handled_kinds):
                violations.append(
                    f"layout '{name.value}' emits IR kind '{kind}' the backend does not handle"
                )
        return violations

    def overlay_completeness_violations(self, handled_kinds: frozenset[str]) -> list[str]:
        """Report every way a registered overlay has drifted from what the backend can render.

        Each overlay's ``to_ir`` is exercised on its ``probe``: a ``transform`` overlay must emit a
        transform fragment (it reshapes existing content, adding no layer), an ``additive`` overlay
        must emit at least one painted layer, and every painted layer kind must be one the backend
        interprets (user stories 21, 30). A non-empty result fails the build.
        """
        violations: list[str] = []
        for type_name, contract in self._overlays.items():
            fragment = contract.to_ir(contract.probe, _PROBE_CTX)
            produced = {layer.kind for layer in fragment.layers}
            if contract.kind is OverlayKind.transform:
                if fragment.transform is None and not fragment.layers:
                    violations.append(f"overlay '{type_name}' (transform) compiles to no IR")
            elif not fragment.layers:
                violations.append(f"overlay '{type_name}' (additive) compiles to no painted layer")
            for kind in sorted(produced - handled_kinds):
                violations.append(
                    f"overlay '{type_name}' emits IR kind '{kind}' the backend does not handle"
                )
        return violations


# A synthetic asset library + Scene used only to exercise each contract's `to_ir` in the
# completeness check (never rendered). `PROBE_ASSET` is public so an overlay plugin can reference
# it from the `probe` instance it hands the registry (e.g. an `insert`'s asset).
PROBE_ASSET: AssetId = "·probe·"
_PROBE_CTX = CompileContext(assets={PROBE_ASSET: Asset(type=AssetType.video, src="·probe·")})


def _probe_scene(name: LayoutName, contract: LayoutContract) -> Scene:
    return Scene(
        id="·probe·",
        start=0.0,
        end=1.0,
        layout=name,
        regions={region: Ref(asset=PROBE_ASSET) for region in contract.regions},
    )


# --- the default registry, lazily populated with the built-in Layouts ---

_default = Registry()
_builtins_loaded = False


def default_registry() -> Registry:
    """The process-wide registry holding the built-in Layouts (``full``, ``split-h``).

    The built-ins live in ``videogen.plugins.layouts`` and register themselves on import; that
    import happens here on first use (after this module is fully loaded) so the kernel registry and
    the plugins do not import each other at module-load time.
    """
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        # Import side effect: the built-in Layouts and overlays register themselves.
        import videogen.plugins.layouts  # noqa: F401
        import videogen.plugins.overlays  # noqa: F401

    return _default


def register_layout(name: LayoutName, contract: LayoutContract) -> None:
    """Register a Layout into the default registry (the entry point the built-in plugins call)."""
    _default.register_layout(name, contract)


def get_layout(name: LayoutName) -> LayoutContract | None:
    """Resolve a Layout's contract from the default registry."""
    return default_registry().get_layout(name)


def layout_regions(name: LayoutName) -> frozenset[RegionName]:
    """The Region slots a Layout exposes, per the default registry (the Validator's source)."""
    return default_registry().layout_regions(name)


def register_overlay(type_name: str, contract: OverlayContract) -> None:
    """Register an overlay type into the default registry (the built-in overlay plugins call it)."""
    _default.register_overlay(type_name, contract)


def get_overlay(type_name: str) -> OverlayContract | None:
    """Resolve an overlay type's contract from the default registry."""
    return default_registry().get_overlay(type_name)
