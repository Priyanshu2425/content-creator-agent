"""AudioDeciderAgent: annotates every scene cut with a SFX decision after authoring completes.

Single-turn agent: receives a view of the Composition with inferred cut_types, returns the same
view annotated with audio fields, which are mapped back onto the Composition's scenes and
audio_budget_summary.

Cut types are inferred deterministically from the existing scene structure — no new Composition
fields are required from the authoring loop. The inference logic uses layout, region assets, and
transition kinds to classify each cut.

NOTE: Audio annotations are stored on the Composition (scene.audio + audio_budget_summary) but
are not yet played in the render. See AUDIO_SFX_WIRING.md for the follow-up task.
"""

from __future__ import annotations

import json
from typing import Any

from videogen import log, tracing
from videogen.agent.model import ModelClient, UserMessage
from videogen.kernel.composition import (
    AudioBudgetSummary,
    Composition,
    LayoutName,
    SceneAudio,
    SoundKind,
    TransitionKind,
    _AudioBudget,
)

_SYSTEM_PROMPT = """\
You are the AudioDeciderAgent, a specialist post-processing agent inside a video editing \
pipeline. Your job is to analyse a Composition and annotate every cut with the correct \
sound effect.

You do not edit video. You do not touch visuals. You only read the composition view and \
write audio annotations back into it.

---

## Your Input

You will receive a JSON object with a "scenes" array. Each scene has:
- cut_id — unique identifier for the cut
- cut_type — one of: talking_head, broll_entry, broll_exit, scene_change, \
screen_recording_reveal, list_item, sentence_transition, caption_appearance, hook, \
major_reveal, transformation, outcome, emotional_moment
- timestamp_ms — when the cut happens in the timeline
- description — a short description of what is happening at this cut

---

## Your Output

Return the same JSON with one new field added to each scene object:

{
  "audio": {
    "sound": "click",
    "reason": "sentence transition in talking head segment",
    "budget_used": { "click": 4, "whoosh": 1, "dramatic_whoosh": 0 }
  }
}

The budget_used field reflects the running totals up to and including this cut.
Also append an audio_budget_summary at the top level.

---

## Decision Rules

Apply in strict priority order. Highest priority rule wins.

### Priority 1 — dramatic_whoosh
Use when cut_type is: major_reveal, transformation, outcome, emotional_moment
Also: hook when timestamp_ms < 3000
Hard budget cap: maximum 3 per reel. If cap reached, downgrade to whoosh and set reason to \
"dramatic_whoosh cap reached (3/3), downgraded to whoosh".

### Priority 2 — whoosh
Use when cut_type is: broll_entry, broll_exit, scene_change, screen_recording_reveal
Also when description signals a significant visual context shift.

### Priority 3 — click (default)
Use for everything else: talking_head, sentence_transition, list_item, caption_appearance.
Any cut where visual context does not significantly change.

---

## Budget Targets

| Sound | Target % | Hard cap |
|---|---|---|
| click | 70–80% | none |
| whoosh | 15–25% | none |
| dramatic_whoosh | 0–5% | 3 per reel |

Append audio_budget_summary at the top level:
{
  "total_cuts": 24,
  "click_count": 18,
  "whoosh_count": 4,
  "dramatic_whoosh_count": 2,
  "click_pct": 75,
  "whoosh_pct": 17,
  "dramatic_whoosh_pct": 8,
  "budget_warnings": []
}

Add a plain-English warning to budget_warnings if any percentage falls outside the target range.

---

## Reason Quality

Every reason must be:
- One sentence, plain English
- Specific to this cut (cite cut_type and/or a detail from description)
- Good: "entering B-roll after talking head explaining the tool"
- Bad: "scene change"

---

## Constraints

- Valid sound values: click, whoosh, dramatic_whoosh — no others.
- Do not modify any field other than adding audio to each scene and audio_budget_summary at top.
- Every scene must receive an audio annotation — no skipping.
- Unknown cut_type defaults to click with reason "unrecognised cut_type, defaulted to click".
- Output valid JSON only. No markdown fences. No commentary outside the JSON.
"""


class AudioDeciderAgent:
    """Annotates Composition scenes with SFX decisions using a single model turn."""

    def __init__(self, client: ModelClient) -> None:
        self._client = client

    def annotate(self, composition: Composition) -> Composition:
        """Return a new Composition with audio annotations on every scene."""
        import time

        view = _build_view(composition)
        user_msg = json.dumps(view, indent=2)
        model = getattr(self._client, "model", "unknown") or "unknown"
        n_scenes = len(composition.scenes)

        t0 = time.monotonic()
        log.get().agent_event_start("AudioDeciderAgent", scene_count=n_scenes, model=model)

        with tracing.agent_span(
            "audio-decider-agent",
            input_summary={"scene_count": n_scenes},
        ):
            with tracing.model_generation(
                "audio-decisions",
                system=_SYSTEM_PROMPT,
                user_message=user_msg,
                model=model,
            ):
                result = self._client.next_turn(
                    system=_SYSTEM_PROMPT,
                    history=[UserMessage(user_msg)],
                    tools=[],
                )
            tracing.update_generation_output(result.text)

        annotated = _apply_annotations(composition, result.text or "")
        n_annotated = sum(1 for s in annotated.scenes if s.audio is not None)
        tracing.update_agent_output({"scenes_annotated": n_annotated})

        budget_line = ""
        budget_summary: dict[str, Any] = {}
        if annotated.audio_budget_summary:
            b = annotated.audio_budget_summary
            budget_line = (
                f"click {b.click_pct}%  whoosh {b.whoosh_pct}%  "
                f"dramatic {b.dramatic_whoosh_pct}%"
            )
            budget_summary = {
                "total_cuts": b.total_cuts,
                "click_count": b.click_count,
                "whoosh_count": b.whoosh_count,
                "dramatic_whoosh_count": b.dramatic_whoosh_count,
                "click_pct": b.click_pct,
                "whoosh_pct": b.whoosh_pct,
                "dramatic_whoosh_pct": b.dramatic_whoosh_pct,
                "warnings": b.budget_warnings,
            }

        log.get().audio_decider_done(n_scenes, n_annotated, budget_line)
        log.get().agent_event_complete(
            "AudioDeciderAgent",
            duration_ms=int((time.monotonic() - t0) * 1000),
            scenes_annotated=n_annotated,
            **budget_summary,
        )
        return annotated


# ---------------------------------------------------------------------------
# Cut-type inference
# ---------------------------------------------------------------------------

def _build_view(composition: Composition) -> dict:
    """Build the enriched scene list the agent reasons over."""
    voiceover_id = composition.voiceover.asset
    transitions_by_scene: dict[str, TransitionKind] = {
        t.after_scene: t.kind for t in composition.transitions
    }

    scenes_view = []
    for idx, scene in enumerate(composition.scenes):
        prev = composition.scenes[idx - 1] if idx > 0 else None
        cut_type = _infer_cut_type(
            scene, idx, voiceover_id, prev, transitions_by_scene
        )
        asset_ids = [ref.asset for ref in scene.regions.values()]
        description = (
            f"layout={scene.layout.value}, "
            f"assets={asset_ids}, "
            f"duration={scene.end - scene.start:.2f}s"
        )
        scenes_view.append({
            "cut_id": scene.id,
            "cut_type": cut_type,
            "timestamp_ms": int(scene.start * 1000),
            "description": description,
        })

    return {"scenes": scenes_view}


def _infer_cut_type(
    scene,
    idx: int,
    voiceover_id: str,
    prev,
    transitions_by_scene: dict[str, TransitionKind],
) -> str:
    start_ms = int(scene.start * 1000)

    # Hook: first scene within the opening 3 seconds
    if idx == 0 and start_ms < 3000:
        return "hook"

    # Scene change: previous scene ends with a whoosh transition
    if prev is not None and transitions_by_scene.get(prev.id) == TransitionKind.whoosh:
        return "scene_change"

    # Determine b-roll presence in this scene and the previous one
    has_broll = _scene_has_broll(scene, voiceover_id)
    prev_has_broll = _scene_has_broll(prev, voiceover_id) if prev is not None else False

    # Split layout always indicates b-roll-over-host
    if scene.layout == LayoutName.split_h:
        return "broll_entry"

    # Full layout with b-roll
    if has_broll:
        return "broll_entry" if not prev_has_broll else "sentence_transition"

    # Full layout with host — returning from b-roll or continuing talking head
    if prev_has_broll:
        return "broll_exit"

    return "talking_head" if idx == 0 else "sentence_transition"


def _scene_has_broll(scene, voiceover_id: str) -> bool:
    if scene is None:
        return False
    return any(ref.asset != voiceover_id for ref in scene.regions.values())


# ---------------------------------------------------------------------------
# Annotation application
# ---------------------------------------------------------------------------

def _apply_annotations(composition: Composition, raw: str) -> Composition:
    """Parse the agent's JSON response and apply audio annotations to the Composition."""
    try:
        data = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        return composition  # agent returned invalid JSON — leave composition unannotated

    # Store the full scene item (not just the audio sub-object) so cut_type is accessible.
    scene_items_by_id: dict[str, dict] = {
        item["cut_id"]: item
        for item in data.get("scenes", [])
        if "cut_id" in item and "audio" in item
    }

    _DRAMATIC_WHOOSH_CAP = 3
    new_scenes = []
    for scene in composition.scenes:
        item = scene_items_by_id.get(scene.id)
        if item is None:
            new_scenes.append(scene)
            continue
        audio = item["audio"]
        try:
            sound_raw = audio["sound"]
            reason = audio.get("reason", "")
            budget_raw = audio.get("budget_used", {})
            dramatic_used = budget_raw.get("dramatic_whoosh", 0)
            remaining = _DRAMATIC_WHOOSH_CAP - dramatic_used

            log.get().audio_decision(
                cut_id=scene.id,
                cut_type=item.get("cut_type", "unknown"),
                timestamp_ms=int(scene.start * 1000),
                sound=sound_raw,
                reason=reason,
                dramatic_whoosh_budget_remaining=remaining,
            )
            if "cap reached" in reason.lower() or "downgraded" in reason.lower():
                log.get().budget_cap_hit(
                    cut_id=scene.id,
                    downgraded_from="dramatic_whoosh",
                    downgraded_to=sound_raw,
                    cap=_DRAMATIC_WHOOSH_CAP,
                )

            scene_audio = SceneAudio(
                sound=SoundKind(sound_raw),
                reason=reason,
                budget_used=_AudioBudget(**budget_raw),
            )
            new_scenes.append(scene.model_copy(update={"audio": scene_audio}))
        except (KeyError, ValueError):
            new_scenes.append(scene)

    summary_data = data.get("audio_budget_summary")
    summary = None
    if summary_data:
        try:
            summary = AudioBudgetSummary(**summary_data)
        except (TypeError, ValueError):
            pass

    return composition.model_copy(update={
        "scenes": new_scenes,
        "audio_budget_summary": summary,
    })


def _parse_json(text: str) -> dict:
    """Extract and parse the first JSON object from the agent's response."""
    import re

    text = text.strip()
    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    # Find outermost {...}
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start: end + 1])
