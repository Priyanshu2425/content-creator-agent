"""Caption style registry: the Python half of the caption library (ADR 0010).

A **caption style** is no longer a closed three-value enum baked into flat IR props. It is a
registered entry ``{id, description, params model, defaults, compile}`` in this registry -- the
single place that knows what each caption visual means on the Python side. ``compile_ir`` resolves a
``Caption.style`` id here and calls the entry's ``compile`` to build the IR pieces of its ``text``
layer (visual props + the opacity/scale keyframe tracks + the emphasis flag), generalizing the old
``compile_caption_style``/``_PROPS``/``_EMPHASIS``.

This mirrors the overlay registry (``kernel/registry.py``): adding a caption visual is a registry
entry plus a pure ``compile``, never a change to ``compile_ir`` or the Composition schema. The set
of registered ids must stay in sync with the TS registry (``backends/remotion/.../captions``); an id
present on one side but not the other is a defect (ADR 0010).

An unknown caption style id is an error by default, downgraded to skip-with-warning under
``strict: false`` -- the same rule as an unknown overlay type (CONTEXT.md "Version / strict mode").
The error-by-default half is enforced at ``Caption`` construction (a field validator); the
strict-false skip-with-warning half is enforced by ``compile_ir`` (which owns the ``strict`` flag).

This module is pure: it depends only on the neutral IR types, never on a backend. The built-in
styles live under ``videogen.plugins.captions.generic`` and register themselves on import; the
default registry imports that package lazily on first use so there is no import cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from videogen.kernel.ir import Transform, Value


@dataclass(frozen=True)
class CompiledCaptionStyle:
    """The IR pieces a caption style contributes to its ``text`` Layer.

    ``props`` are the visual properties the backend paints from; ``opacity``/``transform`` are the
    keyframe tracks the shared sampler drives (kinetic's pop-in rides these -- there is no per-style
    animation code); ``emphasis`` marks a single-cue caption's word as statically bold.
    """

    props: BaseModel
    opacity: Value
    transform: Transform | None
    emphasis: bool


@dataclass(frozen=True)
class CaptionStyleContract:
    """A caption style entry: its description, its typed param schema + defaults, and its compile.

    ``params_model`` is the param schema (e.g. the ``generic`` renderer's visual params);
    ``defaults`` are this style id's param values (so ``pill``/``word-bold``/``kinetic`` are three
    entries that configure one renderer). ``compile`` is the pure function turning validated params
    plus the caption span into the IR pieces.
    """

    description: str
    params_model: type[BaseModel]
    defaults: dict[str, Any]
    compile: Callable[[BaseModel, float, float], CompiledCaptionStyle]

    def resolve_params(self, overrides: dict[str, Any] | None = None) -> BaseModel:
        """Build the validated params for this style, layering ``overrides`` over the defaults."""
        merged = {**self.defaults, **(overrides or {})}
        return self.params_model.model_validate(merged)


class UnknownCaptionStyleError(KeyError):
    """Raised when a caption style id is not registered (the error-by-default path, ADR 0010)."""


class CaptionStyleRegistry:
    """A mutable map of caption style id -> contract, with ``get``/``list``/``compile``.

    The single source of truth for what each caption visual means on the Python side; the TS
    registry must carry the same id set (ADR 0010).
    """

    def __init__(self) -> None:
        self._styles: dict[str, CaptionStyleContract] = {}

    def register(self, style_id: str, contract: CaptionStyleContract) -> None:
        """Register (or replace) a caption style. Purely additive: no schema change (ADR 0010)."""
        self._styles[style_id] = contract

    def get(self, style_id: str) -> CaptionStyleContract | None:
        """Resolve a caption style's contract, or ``None`` if the id is not registered."""
        return self._styles.get(style_id)

    def has(self, style_id: str) -> bool:
        """Whether ``style_id`` is a registered caption style (the validation predicate)."""
        return style_id in self._styles

    def ids(self) -> frozenset[str]:
        """The set of registered caption style ids (the source of truth the TS side must match)."""
        return frozenset(self._styles)

    def list(self) -> list[tuple[str, str]]:
        """Every registered style as ``(id, description)`` pairs, sorted by id (for discovery)."""
        return sorted((style_id, c.description) for style_id, c in self._styles.items())

    def compile(
        self,
        style_id: str,
        start: float,
        end: float,
        *,
        params: dict[str, Any] | None = None,
    ) -> CompiledCaptionStyle:
        """Compile a caption style id into its IR pieces over ``[start, end]``.

        ``params`` overrides the style's defaults (none today: the built-ins are fully configured by
        their defaults). An unknown id raises ``UnknownCaptionStyleError`` -- the error-by-default
        rule. ``compile_ir`` catches it to apply the strict-false skip-with-warning downgrade.
        """
        contract = self._styles.get(style_id)
        if contract is None:
            raise UnknownCaptionStyleError(
                f"unknown caption style {style_id!r}; registered: {sorted(self._styles)}"
            )
        resolved = contract.resolve_params(params)
        return contract.compile(resolved, start, end)


# --- the default registry, lazily populated with the built-in caption styles ---

_default = CaptionStyleRegistry()
_builtins_loaded = False


def default_caption_registry() -> CaptionStyleRegistry:
    """The process-wide caption style registry holding the built-ins (the karaoke generic styles).

    The built-ins live in ``videogen.plugins.captions.generic`` and register themselves on import;
    that import happens here on first use so this module and the plugin do not import each other at
    module-load time (the same lazy pattern as the Layout/overlay registry).
    """
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        import videogen.plugins.captions.generic  # noqa: F401 -- import side effect: registers
        import videogen.plugins.captions.highlight_box  # noqa: F401 -- registers highlight-box
        import videogen.plugins.captions.tiktok  # noqa: F401 -- registers tiktok

    return _default


def register_caption_style(style_id: str, contract: CaptionStyleContract) -> None:
    """Register a caption style into the default registry (the built-in caption plugins call it)."""
    _default.register(style_id, contract)


def get_caption_style(style_id: str) -> CaptionStyleContract | None:
    """Resolve a caption style's contract from the default registry."""
    return default_caption_registry().get(style_id)


def is_registered_caption_style(style_id: str) -> bool:
    """Whether ``style_id`` is a registered caption style (the ``Caption.style`` validator)."""
    return default_caption_registry().has(style_id)


def caption_style_ids() -> frozenset[str]:
    """The registered caption style ids -- the source of truth for the TS-side id set (ADR 0010)."""
    return default_caption_registry().ids()


def compile_caption_style(
    style_id: str, start: float, end: float, *, params: dict[str, Any] | None = None
) -> CompiledCaptionStyle:
    """Compile a caption style id into its IR pieces via the default registry (compile_ir seam)."""
    return default_caption_registry().compile(style_id, start, end, params=params)
