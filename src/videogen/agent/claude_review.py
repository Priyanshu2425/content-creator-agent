"""ClaudeReviewAgent: structural review of the Composition JSON via Claude Code (review.py seam).

Where GeminiReviewAgent *watches the rendered mp4* for motion issues, this reviewer reads the
**Composition JSON itself** (the final document) against the caption/transcript timings and the
Resolver timeline. That catches structural and editorial faults a video-watcher easily misses:

- **scene-to-script alignment** -- does each scene's b-roll/topic match the words actually spoken in
  its time range, or is the cue a beat early/late?
- **dangling assets** -- assets declared but never placed by any scene/overlay (dead weight, and a
  `strict` validation risk);
- **transition symmetry** -- whoosh on the cut *into* a b-roll but a bare hard cut on the way *out*;
- **overlay timing** -- a text hook/overlay that spoils a later stat, or never reinforces it;
- **caption coverage** -- captions that stop before the video ends, or words held far past speech
  cadence;
- **portability** -- absolute local asset paths that break on any other machine.

It implements the same ``ReviewAgent`` seam (it ignores the rendered video and reviews the JSON), so
it is a drop-in for the finalization gate. Gemini stays available for motion review (kept, not
removed) -- this is the default reviewer now.
"""

from __future__ import annotations

import json
import re
from typing import Any

from videogen import log, tracing
from videogen.agent.model import ModelClient, UserMessage
from videogen.agent.review import (
    FeedbackItem,
    ReviewCategory,
    ReviewFeedback,
    Severity,
)
from videogen.kernel.composition import Composition

SYSTEM_PROMPT = """\
You are the review sub-agent for a talking-head-first short-form video generator. You are given the
final Composition as JSON plus a Resolver timeline (what is on screen across time). You DO NOT watch
a video -- you reason about the document itself, which lets you catch structural and editorial bugs a
video-watcher misses. Captions carry per-word timings, so the caption track IS the spoken script on
the timeline; use it to check what is being said at each moment.

Check, rigorously, and report every real problem:

1. SCENE-TO-SCRIPT ALIGNMENT (most important). For each scene, read the caption words that fall in
   its [start, end] range and judge whether the scene's visual (its b-roll asset / split / topic,
   often hinted by its id) actually matches what is being said THEN. A cue that lands a beat before
   or after the line it illustrates is a sync bug -- flag it and say which line it should sit on. If
   the offset is consistent across scenes, say so (it points to an off-by-one in scene assignment).
2. DANGLING ASSETS. List any asset in `assets` not referenced by any scene region or overlay.
3. TRANSITION SYMMETRY. Note cuts that get a transition one way (into a b-roll/split) but a bare hard
   cut the other way (back out), so the style is inconsistent.
4. OVERLAY / TEXT-HOOK TIMING. Does a title/overlay align with the narration under it? Does it spoil
   a later stat or punchline, or fail to reinforce the stat when it is finally spoken? Flag claims
   stronger than the script supports.
5. CAPTION COVERAGE & CADENCE. Captions should cover the whole duration; flag a trailing uncaptioned
   tail, single words held far longer than natural speech (they read as a frozen caption), and
   obvious ASR slips that would display ungrammatical text.
6. CROP REUSE / FRAMING. Identical static crops of the host reused at different source timestamps may
   cut awkwardly through the face/headroom -- flag as framing.
7. PORTABILITY. Absolute local filesystem asset paths (e.g. /Users/...) break on other machines.

Return ONLY a single JSON object, no prose before or after:
{
  "no_actionable_issues": false,
  "items": [
    {"at": 7.1, "until": 11.5, "category": "reel-fit", "severity": "blocking",
     "note": "scene-broll-mandatory plays over '...guidance that wasn't just luck'; the 'mandatory' line is at 7.14-11.5s -- the cue is one beat early."}
  ]
}
Rules:
- category MUST be one of: caption-sync, caption-occlusion, pacing, framing, audio, reel-fit. Pick
  the closest: scene/script alignment, dangling assets, overlay timing, portability -> reel-fit;
  transition asymmetry/rhythm -> pacing; caption coverage/cadence/ASR -> caption-sync; crop/headroom
  -> framing.
- severity is "blocking" (must fix) or "suggestion" (optional polish).
- at/until are timeline seconds; omit until for a point note.
- If the document is genuinely clean, return an empty items array and no_actionable_issues: true.
  Do not invent problems.
"""


class ClaudeReviewAgent:
    """Reviews the Composition JSON with a Claude Code model and returns timestamped feedback."""

    def __init__(self, client: ModelClient | None = None, *, model: str = "claude-sonnet-4-6") -> None:
        self._client = client
        self._model = model

    def review(self, *, video: Any, composition: Composition, timeline: str) -> ReviewFeedback:
        # `video` is accepted to satisfy the ReviewAgent seam but deliberately ignored: this reviewer
        # reads the JSON, not the pixels.
        client = self._ensure_client()
        payload = _build_payload(composition, timeline)
        with tracing.model_generation(
            "claude-review",
            system=SYSTEM_PROMPT,
            user_message=f"scenes={len(composition.scenes)} timeline_chars={len(timeline)}",
            model=self._model,
        ):
            turn = client.next_turn(
                system=SYSTEM_PROMPT, history=[UserMessage(payload)], tools=[]
            )
        feedback = _parse_feedback(turn.text or "")
        tracing.update_generation_output(
            f"{len(feedback.items)} issues, no_actionable_issues={feedback.no_actionable_issues}"
        )
        log.get().finalize_review_done(feedback.no_actionable_issues, len(feedback.items))
        return feedback

    def _ensure_client(self) -> ModelClient:
        if self._client is None:
            from videogen.agent.clients.claude_code import ClaudeCodeClient

            self._client = ClaudeCodeClient(model=self._model)
        return self._client


def _build_payload(composition: Composition, timeline: str) -> str:
    return (
        "Review this final Composition for the problems listed in your instructions. The caption "
        "track carries the spoken script with per-word timings; use it to check what is said when.\n\n"
        f"## Composition (JSON)\n{composition.model_dump_json(by_alias=True, indent=2)}\n\n"
        f"## Timeline (resolver, seconds)\n{timeline}\n\n"
        "Return only the JSON feedback object."
    )


def _parse_feedback(text: str) -> ReviewFeedback:
    """Tolerantly parse the model's reply into ReviewFeedback (empty + clean on unparseable output)."""
    data = _extract_json(text)
    if data is None:
        return ReviewFeedback(items=(), no_actionable_issues=True)
    items: list[FeedbackItem] = []
    for raw in data.get("items", []):
        if not isinstance(raw, dict) or "at" not in raw or "note" not in raw:
            continue
        items.append(
            FeedbackItem(
                at=float(raw["at"]),
                until=None if raw.get("until") is None else float(raw["until"]),
                category=_coerce_category(raw.get("category")),
                severity=_coerce_severity(raw.get("severity")),
                note=str(raw["note"]),
            )
        )
    no_issues = bool(data.get("no_actionable_issues", not items))
    return ReviewFeedback(items=tuple(items), no_actionable_issues=no_issues and not items)


def _coerce_category(value: Any) -> ReviewCategory:
    try:
        return ReviewCategory(value)
    except (ValueError, TypeError):
        return ReviewCategory.reel_fit  # structural issues default to reel-fit


def _coerce_severity(value: Any) -> Severity:
    try:
        return Severity(value)
    except (ValueError, TypeError):
        return Severity.suggestion


def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
