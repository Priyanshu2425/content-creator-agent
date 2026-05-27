"""IR compilation: Compositions compile to the expected neutral IR (ADR 0002).

Snapshot tests in the style the plan prescribes (host-only -> captions -> layouts -> effects). The
host-only Composition produces the simplest IR -- one `media` and one `audio` Layer, no `text`,
constant tracks. The captioned Composition adds one `text` Layer per Caption: `pill`/`word-bold`
are constant within their span, while `kinetic` carries opacity and scale keyframe tracks driving
the pop-in -- the first populated animation in the system. Catching regressions here protects the
backend from bad IR before a render is ever attempted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Composition

SNAPSHOT = Path(__file__).parent / "snapshots" / "host_only_ir.json"
CAPTIONS_SNAPSHOT = Path(__file__).parent / "snapshots" / "host_captions_ir.json"


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


# --- captions (Phase 3) ---


def test_each_caption_compiles_to_a_text_layer_above_the_media(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinds = [layer.kind for layer in ir.layers]
    assert kinds.count("media") == 1
    assert kinds.count("audio") == 1
    assert kinds.count("text") == len(comp.captions)  # one text Layer per Caption

    media = next(layer for layer in ir.layers if layer.kind == "media")
    texts = [layer for layer in ir.layers if layer.kind == "text"]
    # Captions are additive and must paint above the host media (ADR 0001 z convention).
    assert all(layer.z > media.z for layer in texts)


def test_pill_and_word_bold_text_layers_are_constant_within_their_span(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    for layer in ir.layers:
        if layer.kind == "text" and layer.style in ("pill", "word-bold"):
            assert layer.transform is None  # no animation tracks
            assert len(layer.opacity.keyframes) == 1  # constant opacity


def test_kinetic_text_layer_carries_opacity_and_scale_keyframes(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)

    kinetic = next(
        layer for layer in ir.layers if layer.kind == "text" and layer.style == "kinetic"
    )
    caption = next(c for c in comp.captions if c.style.value == "kinetic")

    # Opacity rises 0 -> 1 over a short pop window from the caption start.
    opacity = kinetic.opacity.keyframes
    assert len(opacity) == 2
    assert opacity[0].t == caption.start and opacity[0].value == 0.0
    assert opacity[1].value == 1.0 and caption.start < opacity[1].t <= caption.end

    # Scale springs from small to a settled 1.0 over the same window.
    assert kinetic.transform is not None and kinetic.transform.scale is not None
    scale = kinetic.transform.scale.keyframes
    assert len(scale) == 2
    assert scale[0].t == caption.start and 0.0 < scale[0].value < 1.0
    assert scale[1].value == 1.0 and scale[1].t == opacity[1].t


def test_captions_match_ir_snapshot(
    host_captions_composition: Callable[..., Composition],
) -> None:
    comp = host_captions_composition(src="host.mp4", duration=2.0)
    ir = compile_ir(comp, fps=30, duration=2.0)
    produced = json.loads(ir.model_dump_json(by_alias=True))

    expected = json.loads(CAPTIONS_SNAPSHOT.read_text())
    assert produced == expected
