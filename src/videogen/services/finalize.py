"""Finalization gate: a bounded render -> review -> edit -> re-render loop (Phase 8b, ADR 0004).

Phase 8 stops as soon as the authoring agent reports done and the Composition passes the
``submit_render`` gate -- a first valid pass with no full-motion check. This is the gate ADR 0004
reserved for finalization: render the real video, have a video-capable ``ReviewAgent`` watch the
whole thing, feed its timestamped feedback back through the *existing* Phase 8 authoring loop as
corrective ops, re-render, and re-review -- capped so it cannot loop forever.

Two seams keep the gate decoupled:

- ``VideoRenderer`` -- the full-motion render path. Production wraps RenderService's async
  ``submit_render`` -> poll-status lifecycle (ADR 0003); the gate just calls one method and gets the
  artifact, so it never wedges on the job. This is the *only* consumer of ``render_video``; the
  in-loop authoring channel uses only ``render_still`` (the Phase 8 / 8b division of vision labor).
- ``ReviewAgent`` (in ``agent.review``) -- the video model behind an interface, swappable without
  touching this loop.

The round cap (default 2) is the termination guarantee: it holds even when the reviewer is never
satisfied, in which case the last rendered video at the cap is the shipped artifact. Early
termination on ``no_actionable_issues`` is the optimization, not the guarantee. Every render and
review is recorded on the audit journal; the review-driven edits are journaled by the authoring loop
itself, since corrections are not a new mutation path (ADR 0003 persistence, story 23).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from videogen import log
from videogen.agent.loop import DirectorLoop
from videogen.agent.model import ModelClient
from videogen.agent.perception import Manifest
from videogen.agent.prompts import SYSTEM_PROMPT
from videogen.agent.review import ReviewAgent, ReviewFeedback, format_feedback
from videogen.agent.vision_advice import VisionAdvisor
from videogen.backends.base import RenderBackend
from videogen.kernel import resolver
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Composition
from videogen.stores.composition_store import CompositionStore


class VideoRenderer(Protocol):
    """Renders a Composition to a finished mp4 and returns its location (the full-motion path).

    The production implementation wraps RenderService's async ``submit_render`` -> poll-status
    lifecycle (ADR 0003) and returns once the job is done, so the gate consumes ``render_video``
    without blocking on it in a way that wedges the loop. Keeping the gate dependent on this seam --
    not on RenderService -- preserves the ADR 0003 service boundary and keeps the render engine
    swappable (ADR 0002).
    """

    def render_video(
        self, composition: Composition, *, fps: int, duration: float, name: str | None = None
    ) -> Path:
        """Render ``composition`` to an mp4 and return the artifact's location.

        ``name`` optionally labels the output file (e.g. ``round-1.mp4``)."""
        ...


@dataclass(frozen=True)
class FinalizationResult:
    """The terminal state: the reviewed document, the shipped video, and how finalization ended.

    ``video`` is the last rendered mp4 -- exactly what the reviewer last watched. ``feedback`` is
    the per-round trajectory, and ``terminated_clean`` is True only when the reviewer signalled
    ``no_actionable_issues`` before the round cap (vs. terminating at the cap with notes remaining).
    """

    composition: Composition
    video: Path
    rounds: int
    feedback: tuple[ReviewFeedback, ...]
    terminated_clean: bool


class FinalizationGate:
    """Drives the bounded render/review/edit loop over a first-pass, gate-passing Composition."""

    def __init__(
        self,
        *,
        client: ModelClient,
        builder: Builder,
        manifest: Manifest,
        store: CompositionStore,
        doc_id: str,
        reviewer: ReviewAgent,
        renderer: VideoRenderer,
        backend: RenderBackend | None = None,
        system: str = SYSTEM_PROMPT,
        max_ops: int = 40,
        max_rounds: int = 2,
        artifacts_dir: Path | None = None,
        advisor: VisionAdvisor | None = None,
    ) -> None:
        self._client = client
        self._builder = builder
        self._manifest = manifest
        self._store = store
        self._doc_id = doc_id
        self._reviewer = reviewer
        self._renderer = renderer
        self._backend = backend
        self._system = system
        self._max_ops = max_ops
        self._max_rounds = max_rounds
        self._artifacts_dir = artifacts_dir
        self._advisor = advisor

    def run(self) -> FinalizationResult:
        feedback_history: list[ReviewFeedback] = []
        video: Path | None = None
        terminated_clean = False
        rounds = 0

        for round_index in range(self._max_rounds):
            rounds += 1
            log.get().finalize_round_start(rounds, self._max_rounds)
            video = self._render(rounds)
            feedback = self._review(video, rounds)
            feedback_history.append(feedback)
            if feedback.no_actionable_issues:
                terminated_clean = True
                break
            if round_index == self._max_rounds - 1:
                break  # cap reached: ship the last render even though notes remain (story 25)
            self._apply_edits(feedback, round_index)

        assert video is not None  # max_rounds >= 1, so at least one render always happens
        return FinalizationResult(
            composition=self._builder.composition,
            video=video,
            rounds=rounds,
            feedback=tuple(feedback_history),
            terminated_clean=terminated_clean,
        )

    def _render(self, round_number: int) -> Path:
        log.get().finalize_render_start()
        video = self._renderer.render_video(
            self._builder.composition,
            fps=int(self._manifest.fps),
            duration=self._manifest.duration,
            name=f"round-{round_number}.mp4",
        )
        self._store.note(self._doc_id, op="render_video")
        log.get().finalize_render_done(video)
        return video

    def _review(self, video: Path, round_number: int) -> ReviewFeedback:
        log.get().finalize_review_start()
        timeline = resolver.timeline(self._builder.composition, duration=self._manifest.duration)
        feedback = self._reviewer.review(
            video=video, composition=self._builder.composition, timeline=timeline
        )
        self._store.note(self._doc_id, op="review")
        log.get().finalize_review_done(feedback.no_actionable_issues, len(feedback.items))
        feedback_json = json.dumps(
            [
                {"at": i.at, "until": i.until, "category": i.category.value,
                 "severity": i.severity.value, "note": i.note}
                for i in feedback.items
            ]
        )
        log.get().finalize_feedback(feedback_json)
        if self._artifacts_dir is not None:
            (self._artifacts_dir / f"review-round-{round_number}.json").write_text(
                feedback_json, encoding="utf-8"
            )
        return feedback

    def _apply_edits(self, feedback: ReviewFeedback, round_index: int) -> None:
        """Feed the timestamped notes back through the Phase 8 authoring loop as corrective ops.

        Corrections are not a new mutation path: the same builder, store, and document are reused,
        so each edit is validated immediately and journaled like original authoring (story 16).
        """
        brief = format_feedback(feedback, round_index=round_index, total_rounds=self._max_rounds)
        loop = DirectorLoop(
            self._client,
            self._builder,
            self._manifest,
            self._store,
            self._doc_id,
            backend=self._backend,
            brief=brief,
            system=self._system,
            max_ops=self._max_ops,
            artifacts_dir=self._artifacts_dir,
            advisor=self._advisor,
        )
        loop.run()
