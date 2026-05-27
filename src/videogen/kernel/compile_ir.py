"""Composition -> IR, driving plugins' to_ir via the registry (Phase 2+).

Phase 2 implemented the thinnest slice: a single `full` Scene compiles to one `media` Layer for
the host video and the voiceover compiles to one `audio` Layer, both spanning the master-clock
duration (ADR 0005). Phase 3 adds captions: each Caption compiles to one `text` Layer carrying its
style's visual props, with a high `z` so captions paint above the host media, and -- for `kinetic`
-- the opacity and scale keyframe tracks that drive the pop-in (the system's first populated
animation, evaluated per frame by the backend's keyframe sampler). The IR stays backend-agnostic
(ADR 0002): style differences are baked into the IR by the style presets, so the backend never
branches on a caption style. The registry-driven overlay and layout dispatch arrives in Phase 5.

This module is pure kernel: it depends only on the contract types, never on a service. The caller
supplies `fps` and `duration` as objective facts probed from the media (MediaService lives in the
services layer); the compiler stays a pure Composition -> IR function.
"""

from __future__ import annotations

from videogen.kernel.composition import Composition, RegionName
from videogen.kernel.ir import IR, AudioLayer, Layer, MediaLayer, TextLayer, TextRun
from videogen.plugins.captions.styles import compile_caption_style

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

    # Captions: each compiles to one `text` Layer at its own high `z` (above the media layer), the
    # style baked into visual props plus, for `kinetic`, opacity/scale keyframe tracks. The compiler
    # owns the style->IR mapping so the backend interprets only the three Layer kinds (ADR 0002).
    for caption in composition.captions:
        style = compile_caption_style(caption.style, caption.start, caption.end)
        layers.append(
            TextLayer(
                start=caption.start,
                end=caption.end,
                z=caption.z,
                opacity=style.opacity,
                transform=style.transform,
                runs=[TextRun(text=caption.text, emphasis=style.emphasis)],
                style=caption.style.value,
                props=style.props,
            )
        )

    return IR(width=width, height=height, fps=fps, duration=duration, layers=layers)
