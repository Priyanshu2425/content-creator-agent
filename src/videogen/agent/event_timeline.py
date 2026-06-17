"""Event timeline: the Director's typed classification of meaningful moments (sfx/02, ADR 0008/0009).

The Director owns the event timeline -- it classifies the assembled composition's cuts into typed
events (hook, scene_change, broll_entry/exit, sentence_transition, talking_head) and hands them to
the SFXAgent, which maps them to the sound palette. The classification is pure and deterministic
(formerly inferred inside AudioDeciderAgent); extracting it here makes the Director the single owner
and lets the SFXAgent receive events rather than re-derive them.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.kernel.composition import Composition, LayoutName, Scene, TransitionKind

# The typed events a cut can be. Micro jump-cuts are not events -- only the scene boundaries are.
HOOK = "hook"
SCENE_CHANGE = "scene_change"
BROLL_ENTRY = "broll_entry"
BROLL_EXIT = "broll_exit"
SENTENCE_TRANSITION = "sentence_transition"
TALKING_HEAD = "talking_head"


@dataclass(frozen=True)
class Event:
    """One classified moment on the timeline."""

    scene_id: str
    type: str
    timestamp_ms: int
    description: str


def build_event_timeline(composition: Composition) -> tuple[Event, ...]:
    """Classify each scene boundary into a typed event. Pure: composition in, events out."""
    voiceover_id = composition.voiceover.asset
    transitions_by_scene: dict[str, TransitionKind] = {
        t.after_scene: t.kind for t in composition.transitions
    }
    events: list[Event] = []
    for idx, scene in enumerate(composition.scenes):
        prev = composition.scenes[idx - 1] if idx > 0 else None
        event_type = _classify(scene, idx, voiceover_id, prev, transitions_by_scene)
        asset_ids = [ref.asset for ref in scene.regions.values()]
        description = (
            f"layout={scene.layout.value}, assets={asset_ids}, "
            f"duration={scene.end - scene.start:.2f}s"
        )
        events.append(
            Event(
                scene_id=scene.id,
                type=event_type,
                timestamp_ms=int(scene.start * 1000),
                description=description,
            )
        )
    return tuple(events)


def _classify(
    scene: Scene,
    idx: int,
    voiceover_id: str,
    prev: Scene | None,
    transitions_by_scene: dict[str, TransitionKind],
) -> str:
    start_ms = int(scene.start * 1000)
    if idx == 0 and start_ms < 3000:
        return HOOK
    if prev is not None and transitions_by_scene.get(prev.id) == TransitionKind.whoosh:
        return SCENE_CHANGE
    has_broll = _scene_has_broll(scene, voiceover_id)
    prev_has_broll = _scene_has_broll(prev, voiceover_id) if prev is not None else False
    if scene.layout == LayoutName.split_h:
        return BROLL_ENTRY
    if has_broll:
        return BROLL_ENTRY if not prev_has_broll else SENTENCE_TRANSITION
    if prev_has_broll:
        return BROLL_EXIT
    return TALKING_HEAD if idx == 0 else SENTENCE_TRANSITION


def _scene_has_broll(scene: Scene | None, voiceover_id: str) -> bool:
    if scene is None:
        return False
    return any(ref.asset != voiceover_id for ref in scene.regions.values())
