"""Composition -> IR, driving each plugin's to_ir via the registry (Phase 5).

The compiler walks the Composition and produces the neutral render IR (ADR 0002). It is generic
over arrangements: for each Scene it resolves the Layout through the plugin **registry** and calls
the Layout's pure ``to_ir`` to place Region items as ``media`` layers with the geometry the preset
owns (ADR 0001) -- no per-layout branch here. Captions still compile to ``text`` layers (Phase 3)
and the continuous voiceover to one ``audio`` layer spanning the whole timeline as the master clock
(ADR 0005). Sparse **transitions**, keyed by the Scene they follow, are applied last: a
``crossfade`` becomes an opacity cross-blend on the outgoing and incoming Scenes' layers around the
boundary, expressed through the existing layer kinds so the backend needs no per-transition code.

This module is pure kernel: it depends only on the contract types, the registry, and the plugins it
drives -- never on a service. The caller supplies ``fps`` and ``duration`` as objective facts probed
from the media (MediaService lives in the services layer); the compiler stays a pure
Composition -> IR function.
"""

from __future__ import annotations

from pathlib import Path

from videogen.kernel.composition import Composition, Overlay, RegionName, Scene, TransitionKind
from videogen.kernel.ir import (
    IR,
    AudioLayer,
    Keyframe,
    Layer,
    MediaLayer,
    Rect,
    TextLayer,
    TextRun,
    Transform,
    Value,
)
from videogen.kernel.registry import CompileContext, OverlayKind, Registry, default_registry
from videogen.plugins.captions.styles import compile_caption_style

# v1 output canvas: vertical 9:16, ready for short-form platforms without reformatting.
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920

# SFX files shipped with the repo at sfx/transitions/. Absolute path so _stage_assets can copy
# them into the Remotion public dir at render time, same as any other AudioLayer source.
_SFX_DIR = Path(__file__).resolve().parents[3] / "sfx" / "transitions"

# Durations from sfx/transitions/*.md — used to centre each SFX on the cut boundary.
_SFX_DURATIONS: dict[str, float] = {
    "click": 0.23,
    "whoosh": 0.57,
    "dramatic_whoosh": 1.92,
}


def compile_ir(
    composition: Composition,
    *,
    fps: int,
    duration: float,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> IR:
    """Compile a Composition into the neutral render IR.

    ``duration`` is the voiceover length probed from the master-clock audio (ADR 0005); it sets the
    IR duration and the span of the voiceover audio. ``fps`` is the host recording's frame rate,
    fixing the seconds->frames mapping the backend relies on.
    """
    registry = default_registry()
    ctx = CompileContext(assets=composition.assets)

    # Base layer: resolve each Scene's Layout via the registry and let the plugin place its Region
    # items. Layers are kept grouped by Scene id so sparse transitions can cross-blend a boundary.
    voiceover_src = composition.assets[composition.voiceover.asset].src
    scene_layers: dict[str, list[Layer]] = {}
    for scene in composition.scenes:
        contract = registry.get_layout(scene.layout)
        if contract is None:  # unregistered layout: rejected by the Validator before submit
            continue
        raw_layers = contract.to_ir(scene, ctx)
        # A-roll sync: the host video must seek to scene.start in the source so it stays
        # frame-accurate with the voiceover audio. Remotion's startFrom defaults to 0 when
        # in_point is absent, which drifts every A-roll scene after the first one.
        scene_layers[scene.id] = [
            layer.model_copy(update={"in_point": scene.start})
            if (
                isinstance(layer, MediaLayer)
                and layer.content == "video"
                and layer.src == voiceover_src
                and layer.in_point is None
            )
            else layer
            for layer in raw_layers
        ]

    _apply_transitions(composition, scene_layers, duration=duration)

    # Effect overlays. A transform overlay (zoom/pan) reshapes its target base region in place --
    # its keyframe tracks are bound onto the existing base content and it paints no layer. An
    # additive overlay (insert) contributes a new painted layer, returned here for the paint stack.
    insert_layers = _apply_overlays(composition, scene_layers, registry, ctx)

    layers: list[Layer] = []
    for scene in composition.scenes:
        layers.extend(scene_layers.get(scene.id, []))

    # Voiceover: the master clock, muxed onto the output as a single audio layer spanning the run.
    voiceover_asset = composition.assets[composition.voiceover.asset]
    layers.append(AudioLayer(start=0.0, end=duration, z=0, src=voiceover_asset.src))

    # SFX: one short AudioLayer per scene annotated by AudioDeciderAgent, centred on the scene's
    # start time so the sound straddles the cut boundary. _stage_assets stages the files
    # from sfx/transitions/ into the Remotion public dir at render time like any other asset.
    for scene in composition.scenes:
        if scene.audio is None:
            continue
        sound = scene.audio.sound.value  # "click" | "whoosh" | "dramatic_whoosh"
        sfx_dur = _SFX_DURATIONS.get(sound, 0.23)
        sfx_start = max(0.0, scene.start - sfx_dur / 2)
        sfx_end = min(duration, scene.start + sfx_dur / 2)
        if sfx_end > sfx_start:
            layers.append(
                AudioLayer(
                    start=sfx_start,
                    end=sfx_end,
                    z=0,
                    src=str(_SFX_DIR / f"{sound}.mp3"),
                )
            )

    # Captions: each compiles to one `text` Layer at its own high `z` (above the media layers), the
    # style baked into visual props plus, for `kinetic`, opacity/scale keyframe tracks. The compiler
    # owns the style->IR mapping so the backend interprets only the three Layer kinds (ADR 0002).
    for caption in composition.captions:
        style = compile_caption_style(caption.style, caption.start, caption.end)
        if caption.words:
            # Karaoke line: one run per word carrying its spoken window, so the backend can
            # highlight the current word. The whole line is on screen for the caption's span.
            runs = [
                TextRun(text=word.text, start=word.start, end=word.end) for word in caption.words
            ]
        else:
            # A plain single cue (no per-word timing): one static run.
            runs = [TextRun(text=caption.text, emphasis=style.emphasis)]
        layers.append(
            TextLayer(
                start=caption.start,
                end=caption.end,
                z=caption.z,
                opacity=style.opacity,
                transform=style.transform,
                runs=runs,
                style=caption.style.value,
                props=style.props,
            )
        )

    # Additive inserts join the flat layer list; the backend paints everything in z order, so an
    # insert sits in the one shared z space alongside captions (CONTEXT.md "z (paint order)").
    layers.extend(insert_layers)

    return IR(width=width, height=height, fps=fps, duration=duration, layers=layers)


def _apply_transitions(
    composition: Composition, scene_layers: dict[str, list[Layer]], *, duration: float
) -> None:
    """Apply the sparse, ``afterScene``-keyed transitions in place on the per-Scene layer groups.

    A cut is the absence of an entry and needs no work. A ``crossfade`` after Scene A blends across
    A's boundary (its end): A's layers are held on screen and faded 1->0 over the window, while the
    next Scene's layers fade 0->1 over the same window -- an opacity cross-blend expressed through
    the existing layer kinds (ADR 0002). Keying off the Scene id, not list position, means
    reordering the Scenes cannot misplace the crossfade (ADR 0001, story 21).
    """
    by_id = {scene.id: scene for scene in composition.scenes}
    ordered = sorted(composition.scenes, key=lambda s: (s.start, s.end))
    next_id = {ordered[i].id: ordered[i + 1].id for i in range(len(ordered) - 1)}

    for transition in composition.transitions:
        if transition.kind is TransitionKind.whoosh:
            # Hard visual smash cut — no opacity blend and NO sound (ADR 0009): the whoosh
            # transition is purely visual. Any whoosh sound is owned solely by the SFX layer
            # (scene.audio, placed by the SFXAgent), so the two never double-fire on a cut.
            continue
        if transition.kind is not TransitionKind.crossfade:
            continue
        outgoing = by_id.get(transition.after_scene)
        if outgoing is None:  # dangling afterScene: rejected by the Validator before submit
            continue
        boundary = outgoing.end
        fade_end = min(boundary + transition.duration, duration)
        if fade_end <= boundary:  # no room (boundary at the master clock's end): nothing to blend
            continue

        scene_layers[outgoing.id] = [
            _ramp_opacity(layer, boundary, fade_end, start_value=1.0, end_value=0.0, extend=True)
            for layer in scene_layers.get(outgoing.id, [])
        ]
        incoming_id = next_id.get(outgoing.id)
        if incoming_id is not None:
            scene_layers[incoming_id] = [
                _ramp_opacity(
                    layer, boundary, fade_end, start_value=0.0, end_value=1.0, extend=False
                )
                for layer in scene_layers.get(incoming_id, [])
            ]


def _apply_overlays(
    composition: Composition,
    scene_layers: dict[str, list[Layer]],
    registry: Registry,
    ctx: CompileContext,
) -> list[Layer]:
    """Drive each overlay's plugin via the registry and assemble the results by declared kind.

    A ``transform`` overlay's emitted tracks are bound onto the base content of its target region
    in place (mutating ``scene_layers``); it paints no layer. An ``additive`` overlay's painted
    layers are collected and returned for the flat layer list. The classification comes from the
    contract, not from the type name (ADR 0001). An unregistered type is skipped (the Validator
    rejects an unknown type before submit, per ``strict`` mode).
    """
    inserts: list[Layer] = []
    for overlay in composition.overlays:
        contract = registry.get_overlay(overlay.type)
        if contract is None:
            continue
        fragment = contract.to_ir(overlay, ctx)
        if contract.kind is OverlayKind.transform:
            if fragment.transform is not None:
                _bind_transform(overlay, fragment.transform, composition, scene_layers, registry)
        else:
            inserts.extend(fragment.layers)
    return inserts


def _bind_transform(
    overlay: Overlay,
    transform: Transform,
    composition: Composition,
    scene_layers: dict[str, list[Layer]],
    registry: Registry,
) -> None:
    """Merge a transform overlay's tracks onto the base media of its target region, in place.

    Resolved per the scene covering each sub-span: for every Scene overlapping the overlay's span,
    the target region's geometry selects the base ``media`` layer(s) to reshape (a ``full`` target
    is the full-frame layer; ``top``/``bottom`` match the split's region rect). No new layer is
    added, so the reshape never touches the captions or inserts painted above the region.
    """
    for scene in composition.scenes:
        if not _overlaps(overlay.start, overlay.end, scene.start, scene.end):
            continue
        target_rect = _target_rect(scene, overlay.target, registry)
        scene_layers[scene.id] = [
            _merge_transform(layer, transform)
            if _is_target(layer, overlay.target, target_rect)
            else layer
            for layer in scene_layers.get(scene.id, [])
        ]


def _target_rect(scene: Scene, target: RegionName, registry: Registry) -> Rect | None:
    """The destination rect of the target region in ``scene``; ``None`` means the full frame."""
    if target is RegionName.full:
        return None
    contract = registry.get_layout(scene.layout)
    if contract is None:
        return None
    return contract.region_rects(scene).get(target)


def _is_target(layer: Layer, target: RegionName, target_rect: Rect | None) -> bool:
    """Whether ``layer`` is the base content the transform should reshape for this target region."""
    if not isinstance(layer, MediaLayer):
        return False  # only base media is reshaped; never an audio or text layer
    if target is RegionName.full:
        return layer.rect is None  # the full-frame base layer
    return target_rect is not None and layer.rect == target_rect


def _merge_transform(layer: Layer, overlay_transform: Transform) -> Layer:
    """Return a copy of ``layer`` with the overlay's transform tracks composed onto its own.

    Field-wise so a zoom (scale) and a pan (translate) targeting the same region accumulate rather
    than overwrite. The base media's existing transform (none, this phase) is preserved per axis.
    """
    base = layer.transform or Transform()
    merged = Transform(
        scale=overlay_transform.scale or base.scale,
        translate_x=overlay_transform.translate_x or base.translate_x,
        translate_y=overlay_transform.translate_y or base.translate_y,
    )
    return layer.model_copy(update={"transform": merged})


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """Half-open overlap: a touching boundary is not an overlap (matches the Validator)."""
    return a_start < b_end and b_start < a_end


def _ramp_opacity(
    layer: Layer,
    start_t: float,
    end_t: float,
    *,
    start_value: float,
    end_value: float,
    extend: bool,
) -> Layer:
    """Return a copy of ``layer`` whose opacity ramps ``start_value -> end_value`` over the window.

    The sampler clamps outside the keyframes, so a layer that begins before ``start_t`` holds
    ``start_value`` until the window. ``extend`` lengthens the outgoing layer to ``end_t`` so it
    stays on screen, blending under the incoming layer, past the boundary where its Scene ended.
    """
    opacity = Value(
        keyframes=[Keyframe(t=start_t, value=start_value), Keyframe(t=end_t, value=end_value)]
    )
    updates: dict[str, object] = {"opacity": opacity}
    if extend:
        updates["end"] = end_t
    return layer.model_copy(update=updates)
