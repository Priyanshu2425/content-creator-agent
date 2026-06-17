"""Event timeline builder (sfx/02): pure classification of cuts into typed events."""

from __future__ import annotations

from videogen.agent.event_timeline import build_event_timeline
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, LayoutName, TransitionKind


def _builder() -> Builder:
    return Builder.new(
        voiceover="host",
        duration=20.0,
        assets={
            "host": Asset(type=AssetType.video, src="host.mp4"),
            "broll": Asset(type=AssetType.image, src="broll.png"),
        },
    )


def test_first_scene_in_the_opening_is_a_hook() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    events = build_event_timeline(b.composition)
    assert events[0].type == "hook"
    assert events[0].scene_id == "s0"


def test_scene_after_a_whoosh_transition_is_a_scene_change() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    b.add_scene(LayoutName.full, 4.0, 8.0, id="s1")
    b.fill_region("s1", "full", "host")  # type: ignore[arg-type]
    b.add_transition("s0", TransitionKind.whoosh)
    events = build_event_timeline(b.composition)
    assert events[1].type == "scene_change"


def test_broll_scene_is_a_broll_entry() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    b.add_scene(LayoutName.full, 4.0, 8.0, id="s1")
    b.fill_region("s1", "full", "broll")  # type: ignore[arg-type]
    events = build_event_timeline(b.composition)
    assert events[1].type == "broll_entry"


def test_timestamps_are_in_milliseconds_at_the_scene_start() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", "full", "host")  # type: ignore[arg-type]
    b.add_scene(LayoutName.full, 5.0, 9.0, id="s1")
    b.fill_region("s1", "full", "host")  # type: ignore[arg-type]
    events = build_event_timeline(b.composition)
    assert events[1].timestamp_ms == 5000
