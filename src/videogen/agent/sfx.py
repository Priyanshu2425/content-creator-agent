"""SFXAgent: the single SFX authority (sfx/02, ADR 0009).

Recast from AudioDeciderAgent. It receives the Director-owned **event timeline** and maps each event
to the brand-kit sound palette within the density budget -- deterministically (the doc's "map, don't
think"), so it is robust and unit-testable without a model. It is the *only* source of SFX: the
whoosh transition is silent (ADR 0009), so a placed whoosh and a transition can never double-fire.

v1 is cut-bound: placements attach to scene cuts via ``scene.audio`` (the already-wired audio IR
path) and draw only from the three real palette sounds (click / whoosh / dramatic_whoosh).
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen import log
from videogen.agent.brand_kit import SfxBudget
from videogen.agent.event_timeline import Event, build_event_timeline
from videogen.kernel.composition import (
    AudioBudgetSummary,
    Composition,
    SceneAudio,
    SoundKind,
    _AudioBudget,
)

# Deterministic event-type -> sound mapping (the routine layer). `reveal`/emphasis candidates are
# subject to the density pass below; everything else is the default click.
_DRAMATIC = {"major_reveal", "transformation", "outcome", "emotional_moment", "reveal"}
_WHOOSH = {"broll_entry", "broll_exit", "scene_change", "screen_recording_reveal"}

_DRAMATIC_CAP = 3  # at most three dramatic_whoosh per reel
_SFX_DURATIONS_MS = {"click": 230, "whoosh": 570, "dramatic_whoosh": 1920}


@dataclass(frozen=True)
class Placement:
    scene_id: str
    timestamp_ms: int
    sound: SoundKind
    reason: str


class SFXAgent:
    """Maps a typed event timeline onto the sound palette within the density budget (deterministic)."""

    def __init__(self, budget: SfxBudget | None = None) -> None:
        self._budget = budget or SfxBudget()

    def place(self, events: tuple[Event, ...]) -> list[Placement]:
        """Choose a palette sound per meaningful event, then enforce the density budget.

        Restraint is the job: events too close together (within ``min_gap_ms``) collapse to the
        single stronger one, and the per-10s cap is enforced. Silence is the default."""
        proposed = [self._propose(e) for e in events]
        return self._enforce_density(proposed)

    def annotate(self, composition: Composition) -> Composition:
        """Apply SFX to the composition by setting ``scene.audio`` on the placed cuts (cut-bound v1).

        The single SFX authority: builds the event timeline, places sounds, writes ``scene.audio`` and
        the top-level ``audio_budget_summary``. Scenes already carrying audio (e.g. set in-loop by a
        ``dispatch_sfx`` call) are left untouched, so SFX is never double-applied."""
        events = build_event_timeline(composition)
        placements = {p.scene_id: p for p in self.place(events)}
        counts = {"click": 0, "whoosh": 0, "dramatic_whoosh": 0}

        new_scenes = []
        for scene in composition.scenes:
            if scene.audio is not None:  # already placed (in-loop dispatch) -- respect it
                new_scenes.append(scene)
                counts[scene.audio.sound.value] += 1
                continue
            placement = placements.get(scene.id)
            if placement is None:
                new_scenes.append(scene)
                continue
            counts[placement.sound.value] += 1
            audio = SceneAudio(
                sound=placement.sound,
                reason=placement.reason,
                budget_used=_AudioBudget(**counts),
            )
            new_scenes.append(scene.model_copy(update={"audio": audio}))

        summary = _summarize(counts)
        annotated = composition.model_copy(
            update={"scenes": new_scenes, "audio_budget_summary": summary}
        )
        log.get().agent_event_complete(
            "SFXAgent",
            duration_ms=0,
            total_cuts=summary.total_cuts,
            click=summary.click_count,
            whoosh=summary.whoosh_count,
            dramatic_whoosh=summary.dramatic_whoosh_count,
        )
        return annotated

    def _propose(self, event: Event) -> Placement:
        if event.type in _DRAMATIC or (event.type == "hook" and event.timestamp_ms < 3000):
            return Placement(event.scene_id, event.timestamp_ms, SoundKind.dramatic_whoosh, f"{event.type}")
        if event.type in _WHOOSH:
            return Placement(event.scene_id, event.timestamp_ms, SoundKind.whoosh, f"{event.type}")
        return Placement(event.scene_id, event.timestamp_ms, SoundKind.click, f"{event.type}")

    def _enforce_density(self, proposed: list[Placement]) -> list[Placement]:
        """Drop near-neighbours (within ``min_gap_ms``), enforce the dramatic cap and per-10s cap."""
        kept: list[Placement] = []
        dramatic = 0
        for p in sorted(proposed, key=lambda x: x.timestamp_ms):
            if kept and p.timestamp_ms - kept[-1].timestamp_ms < self._budget.min_gap_ms:
                # too close to the previous kept sound: keep the stronger, drop the weaker
                if _rank(p.sound) <= _rank(kept[-1].sound):
                    continue
                kept.pop()
            sound = p.sound
            reason = p.reason
            if sound is SoundKind.dramatic_whoosh:
                if dramatic >= _DRAMATIC_CAP:
                    sound = SoundKind.whoosh
                    reason = f"{p.reason} (dramatic cap reached, downgraded)"
                else:
                    dramatic += 1
            kept.append(Placement(p.scene_id, p.timestamp_ms, sound, reason))
        return _enforce_per_10s(kept, self._budget.max_per_10s)


def _rank(sound: SoundKind) -> int:
    return {SoundKind.click: 0, SoundKind.whoosh: 1, SoundKind.dramatic_whoosh: 2}[sound]


def _enforce_per_10s(placements: list[Placement], max_per_10s: int) -> list[Placement]:
    """Keep at most ``max_per_10s`` sounds in any rolling 10s window, preferring stronger sounds."""
    kept: list[Placement] = []
    for p in placements:
        window = [k for k in kept if p.timestamp_ms - k.timestamp_ms < 10_000]
        if len(window) >= max_per_10s:
            weakest = min(window, key=lambda k: _rank(k.sound))
            if _rank(p.sound) <= _rank(weakest.sound):
                continue
            kept.remove(weakest)
        kept.append(p)
    return kept


def _summarize(counts: dict[str, int]) -> AudioBudgetSummary:
    total = sum(counts.values())
    pct = lambda n: round(n / total * 100) if total else 0  # noqa: E731
    return AudioBudgetSummary(
        total_cuts=total,
        click_count=counts["click"],
        whoosh_count=counts["whoosh"],
        dramatic_whoosh_count=counts["dramatic_whoosh"],
        click_pct=pct(counts["click"]),
        whoosh_pct=pct(counts["whoosh"]),
        dramatic_whoosh_pct=pct(counts["dramatic_whoosh"]),
    )
