"""IR compilation: the host-only Composition compiles to the expected neutral IR (ADR 0002).

A snapshot test in the style the plan prescribes: the simplest Composition produces the simplest
IR -- one `media` Layer and one `audio` Layer spanning the voiceover duration, no `text` Layers,
constant (no-keyframe) tracks. The snapshot grows in Phase 3 when captions add `text` Layers and
kinetic animation populates tracks. Catching regressions here protects the backend from bad IR.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Composition

SNAPSHOT = Path(__file__).parent / "snapshots" / "host_only_ir.json"


def test_host_only_compiles_to_one_media_and_one_audio_layer(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinds = [layer.kind for layer in ir.layers]
    assert kinds.count("media") == 1
    assert kinds.count("audio") == 1
    assert "text" not in kinds  # captions are Phase 3


def test_host_only_media_layer_is_full_frame_for_the_whole_timeline(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    media = next(layer for layer in ir.layers if layer.kind == "media")
    assert media.start == 0.0
    assert media.end == 2.0
    assert media.transform is None  # no keyframes this phase; sampler runs its constant path


def test_voiceover_sets_ir_duration_and_audio_span(
    host_only_composition: Callable[..., Composition],
) -> None:
    # The voiceover is the master clock (ADR 0005): it defines the composition's duration.
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    audio = next(layer for layer in ir.layers if layer.kind == "audio")
    assert ir.duration == 2.0
    assert (audio.start, audio.end) == (0.0, 2.0)


def test_host_only_matches_ir_snapshot(
    host_only_composition: Callable[..., Composition],
) -> None:
    comp = host_only_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(SNAPSHOT.read_text())
    assert produced == expected
