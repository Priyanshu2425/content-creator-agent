"""Composition -> IR, driving plugins' to_ir via the registry (Phase 2+).

Phase 2 implements the thinnest slice: a single `full` Scene compiles to one `media` Layer for
the host video and the voiceover compiles to one `audio` Layer, both spanning the master-clock
duration (ADR 0005). The IR is backend-agnostic (ADR 0002) -- it carries timed layers of
primitives and nothing Remotion-specific. No `text` Layers and no populated keyframe tracks are
produced this phase; captions and animation arrive in Phase 3, and the registry-driven overlay
and layout dispatch arrives in Phase 5.

This module is pure kernel: it depends only on the contract types, never on a service. The caller
supplies `fps` and `duration` as objective facts probed from the media (MediaService lives in the
services layer); the compiler stays a pure Composition -> IR function.
"""

from __future__ import annotations

from videogen.kernel.composition import Composition, RegionName
from videogen.kernel.ir import IR, AudioLayer, Layer, MediaLayer

# v1 output canvas: vertical 9:16, ready for short-form platforms without reformatting.
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920


def compile_ir(
    composition: Composition,
    *,
    fps: int,
    duration: float,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> IR:
    """Compile a Composition into the neutral render IR.

    `duration` is the voiceover length probed from the master-clock audio (ADR 0005); it sets the
    IR duration and the span of both the base media and the voiceover audio. `fps` is the host
    recording's frame rate, fixing the seconds->frames mapping the backend relies on.
    """
    layers: list[Layer] = []

    # Base layer: each `full` Scene's `full` Region becomes a full-frame media layer. Phase 2
    # handles only the `full` layout; `split-h` and its regions arrive in Phase 5.
    for scene in composition.scenes:
        ref = scene.regions[RegionName.full]
        asset = composition.assets[ref.asset]
        layers.append(
            MediaLayer(
                start=scene.start,
                end=scene.end,
                z=0,
                src=asset.src,
                in_point=ref.in_point,
            )
        )

    # Voiceover: the master clock, muxed onto the output as a single audio layer.
    voiceover_asset = composition.assets[composition.voiceover.asset]
    layers.append(
        AudioLayer(
            start=0.0,
            end=duration,
            z=0,
            src=voiceover_asset.src,
        )
    )

    return IR(width=width, height=height, fps=fps, duration=duration, layers=layers)
