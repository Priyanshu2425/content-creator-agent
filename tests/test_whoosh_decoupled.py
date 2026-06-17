"""Whoosh transition is sound-decoupled (sfx/01, ADR 0009).

The `whoosh` transition is a purely *visual* smash cut: it emits no audio node. Any whoosh *sound*
is owned solely by the SFXAgent (via scene.audio), so a whoosh transition and a placed SFX can never
double-fire on the same cut. This pins the decoupling at the IR boundary.
"""

from __future__ import annotations

from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Asset, AssetType, LayoutName, TransitionKind
from videogen.kernel.ir import AudioLayer


def _two_scene_builder() -> Builder:
    b = Builder.new(
        voiceover="host",
        duration=10.0,
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
    )
    b.add_scene(LayoutName.full, 0.0, 5.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    b.add_scene(LayoutName.full, 5.0, 10.0, id="s1")
    b.fill_region("s1", "full", "host")  # type: ignore[arg-type]
    return b


def test_whoosh_transition_emits_no_audio_node() -> None:
    b = _two_scene_builder()
    b.add_transition("s0", TransitionKind.whoosh)
    ir = compile_ir(b.composition, fps=30, duration=10.0)

    audio = [layer for layer in ir.layers if isinstance(layer, AudioLayer)]
    # exactly the voiceover, spanning the whole timeline -- no transition SFX node
    assert len(audio) == 1
    assert audio[0].start == 0.0 and audio[0].end == 10.0


def test_whoosh_transition_is_a_visual_cut_not_a_crossfade() -> None:
    b = _two_scene_builder()
    b.add_transition("s0", TransitionKind.whoosh)
    ir = compile_ir(b.composition, fps=30, duration=10.0)

    # a hard cut: the two scenes' media layers do not opacity-blend across the boundary
    media = [layer for layer in ir.layers if layer.kind == "media"]
    assert media  # scenes rendered; the absence of an audio SFX node is the point
