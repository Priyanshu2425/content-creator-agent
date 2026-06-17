"""SFXAgent (sfx/02): the single SFX authority -- deterministic event->palette mapping + density."""

from __future__ import annotations

from videogen.agent.brand_kit import SfxBudget
from videogen.agent.event_timeline import Event
from videogen.agent.sfx import SFXAgent
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, LayoutName, SoundKind


def _ev(scene_id: str, type_: str, ms: int) -> Event:
    return Event(scene_id=scene_id, type=type_, timestamp_ms=ms, description="")


def test_event_types_map_to_the_expected_palette_sounds() -> None:
    agent = SFXAgent(SfxBudget(min_gap_ms=0, max_per_10s=99))
    placements = {
        p.scene_id: p.sound
        for p in agent.place(
            (
                _ev("s0", "hook", 0),
                _ev("s1", "broll_entry", 5000),
                _ev("s2", "talking_head", 12000),
            )
        )
    }
    assert placements["s0"] is SoundKind.dramatic_whoosh  # hook opens with the big sound
    assert placements["s1"] is SoundKind.whoosh
    assert placements["s2"] is SoundKind.click


def test_dramatic_whoosh_is_capped_and_downgraded() -> None:
    agent = SFXAgent(SfxBudget(min_gap_ms=0, max_per_10s=99))
    events = tuple(_ev(f"s{i}", "major_reveal", i * 5000) for i in range(5))
    sounds = [p.sound for p in agent.place(events)]
    assert sounds.count(SoundKind.dramatic_whoosh) == 3  # cap
    assert sounds.count(SoundKind.whoosh) == 2  # the rest downgraded


def test_density_drops_sounds_too_close_together() -> None:
    agent = SFXAgent(SfxBudget(min_gap_ms=2500, max_per_10s=99))
    # two clicks 1s apart -> only one survives the min-gap
    placements = agent.place((_ev("s0", "talking_head", 0), _ev("s1", "talking_head", 1000)))
    assert len(placements) == 1


def test_annotate_sets_scene_audio_and_a_budget_summary() -> None:
    b = Builder.new(
        voiceover="host", duration=20.0, assets={"host": Asset(type=AssetType.video, src="h.mp4")}
    )
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]

    annotated = SFXAgent().annotate(b.composition)

    assert annotated.scenes[0].audio is not None
    assert annotated.scenes[0].audio.sound is SoundKind.dramatic_whoosh  # opening hook
    assert annotated.audio_budget_summary is not None
    assert annotated.audio_budget_summary.total_cuts == 1


def test_annotate_respects_pre_existing_scene_audio() -> None:
    from videogen.kernel.composition import SceneAudio, _AudioBudget

    b = Builder.new(
        voiceover="host", duration=20.0, assets={"host": Asset(type=AssetType.video, src="h.mp4")}
    )
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    pre = b.composition.model_copy(
        update={
            "scenes": [
                b.composition.scenes[0].model_copy(
                    update={
                        "audio": SceneAudio(
                            sound=SoundKind.click, reason="preset", budget_used=_AudioBudget()
                        )
                    }
                )
            ]
        }
    )

    annotated = SFXAgent().annotate(pre)
    assert annotated.scenes[0].audio.sound is SoundKind.click  # left untouched
    assert annotated.scenes[0].audio.reason == "preset"
