"""Finalization gate: render -> review -> edit -> re-render, bounded (Phase 8b, ADR 0004/0003).

The video reviewer is non-deterministic and external, so these tests drive the *gate's control flow*
with a fake ``ReviewAgent`` and a fake ``VideoRenderer``, never a real video model. They assert the
externally observable behavior the phase promises: the loop renders the full video and reviews it,
feeds timestamped feedback back through the Phase 8 authoring loop as corrective ops, re-renders,
and terminates exactly when the reviewer is clean or the round cap is hit; the gate uses
``render_video`` while the in-loop authoring channel still uses only ``render_still``; and the gate
depends only on the ``ReviewAgent`` interface so the concrete video model is swappable.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from pathlib import Path

from videogen.agent.model import AssistantTurn, HistoryItem, ToolCall, ToolSpec
from videogen.agent.perception import AssetFact, MediaManifest
from videogen.agent.review import (
    FeedbackItem,
    ReviewCategory,
    ReviewFeedback,
    Severity,
)
from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Asset, AssetType, Composition, LayoutName, RegionName
from videogen.kernel.ir import IR
from videogen.services.finalize import FinalizationGate
from videogen.stores.composition_store import CompositionStore

_ids = itertools.count()


def call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=f"c{next(_ids)}", name=name, args=args)


def turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(tool_calls=calls)


class ScriptedClient:
    """The authoring agent: emits a fixed sequence of edit turns across feedback rounds."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self.calls = 0

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.calls += 1
        return self._turns.pop(0) if self._turns else AssistantTurn()


class CountingBackend:
    """Counts each render path so the test can prove the gate/loop division of vision labor."""

    def __init__(self) -> None:
        self.still = 0
        self.video = 0

    def render_video(self, ir: IR, out_path: Path) -> Path:
        self.video += 1
        out_path.write_bytes(b"fake-mp4")
        return out_path

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:
        self.still += 1
        out_path.write_bytes(b"fake-png")
        return out_path


class FakeRenderer:
    """A VideoRenderer that compiles the IR and renders the full video through a backend."""

    def __init__(self, backend: CountingBackend, out_dir: Path) -> None:
        self._backend = backend
        self._out_dir = out_dir
        self.calls = 0

    def render_video(self, composition: Composition, *, fps: int, duration: float) -> Path:
        ir = compile_ir(composition, fps=fps, duration=duration)
        out = self._out_dir / f"render-{self.calls}.mp4"
        self.calls += 1
        return self._backend.render_video(ir, out)


class ScriptedReviewer:
    """Returns a scripted sequence of review passes; records each video it was handed to watch."""

    def __init__(self, passes: list[ReviewFeedback]) -> None:
        self._passes = list(passes)
        self.videos: list[Path] = []

    def review(self, *, video: Path, composition: Composition, timeline: str) -> ReviewFeedback:
        self.videos.append(video)
        return self._passes.pop(0) if self._passes else _CLEAN


class AlwaysCleanReviewer:
    """A different ReviewAgent implementation: never finds an issue (the swap-seam foil)."""

    def __init__(self) -> None:
        self.calls = 0

    def review(self, *, video: Path, composition: Composition, timeline: str) -> ReviewFeedback:
        self.calls += 1
        return _CLEAN


_CLEAN = ReviewFeedback(items=(), no_actionable_issues=True)


def _blocking(note: str) -> ReviewFeedback:
    return ReviewFeedback(
        items=(
            FeedbackItem(
                at=0.6,
                category=ReviewCategory.caption_sync,
                severity=Severity.blocking,
                note=note,
            ),
        ),
        no_actionable_issues=False,
    )


class _Word:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


class _Transcript:
    def __init__(self, words: list[_Word]) -> None:
        self.words = words


def make_manifest() -> MediaManifest:
    return MediaManifest(
        assets=(AssetFact("host", "video", "host.mp4", 2.0, 1080, 1920),),
        voiceover="host",
        duration=2.0,
        fps=30.0,
        transcript=_Transcript([_Word("hello", 0.1, 0.5), _Word("world", 0.6, 1.0)]),
    )


def seeded_builder() -> Builder:
    """A first-pass authored document that already passes the submit-render gate."""
    builder = Builder.new(
        voiceover="host", duration=2.0, assets={"host": Asset(type=AssetType.video, src="host.mp4")}
    )
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    return builder


def make_gate(
    client: object,
    reviewer: object,
    renderer: object,
    *,
    backend: object | None = None,
    builder: Builder | None = None,
    max_rounds: int = 2,
) -> tuple[FinalizationGate, Builder, CompositionStore, str]:
    builder = builder or seeded_builder()
    store = CompositionStore()
    doc_id = store.open(builder.composition)
    gate = FinalizationGate(
        client=client,  # type: ignore[arg-type]
        builder=builder,
        manifest=make_manifest(),
        store=store,
        doc_id=doc_id,
        reviewer=reviewer,  # type: ignore[arg-type]
        renderer=renderer,  # type: ignore[arg-type]
        backend=backend,  # type: ignore[arg-type]
        max_rounds=max_rounds,
    )
    return gate, builder, store, doc_id


def test_a_clean_first_pass_renders_once_and_runs_no_edit_rounds(tmp_path: Path) -> None:
    backend = CountingBackend()
    renderer = FakeRenderer(backend, tmp_path)
    reviewer = ScriptedReviewer([_CLEAN])
    client = ScriptedClient([])  # the agent is never asked to edit a good first pass
    gate, _builder, store, doc_id = make_gate(client, reviewer, renderer, backend=backend)

    result = gate.run()

    assert result.terminated_clean
    assert result.rounds == 1
    assert renderer.calls == 1  # exactly one render; a good video is not re-rendered
    assert client.calls == 0  # zero edit rounds
    assert result.video is not None
    assert [e.op for e in store.journal(doc_id)] == ["render_video", "review"]


def test_a_blocking_round_drives_edits_then_terminates_when_clean(tmp_path: Path) -> None:
    backend = CountingBackend()
    renderer = FakeRenderer(backend, tmp_path)
    reviewer = ScriptedReviewer([_blocking("caption out of sync"), _CLEAN])
    client = ScriptedClient(
        [
            turn(call("add_caption", text="world", start=0.6, end=1.0, style="pill")),
            turn(call("finish")),
        ]
    )
    gate, builder, store, doc_id = make_gate(client, reviewer, renderer, backend=backend)

    result = gate.run()

    assert result.terminated_clean  # stopped as soon as the reviewer signalled clean
    assert result.rounds == 2  # one blocking round + one clean round
    assert renderer.calls == 2  # rendered, edited, re-rendered
    assert builder.can_submit_render()  # the post-edit document still passes the gate
    assert len(builder.composition.captions) == 1  # the corrective op landed
    ops = [e.op for e in store.journal(doc_id)]
    assert ops.count("render_video") == 2 and ops.count("review") == 2
    assert "add_caption" in ops  # the review-driven edit is journaled like any authoring op


def test_the_round_cap_terminates_even_when_the_reviewer_is_never_satisfied(tmp_path: Path) -> None:
    backend = CountingBackend()
    renderer = FakeRenderer(backend, tmp_path)
    reviewer = ScriptedReviewer([_blocking("still off"), _blocking("still off")])
    client = ScriptedClient(
        [
            turn(call("add_caption", text="x", start=0.1, end=0.2, style="pill")),
            turn(call("finish")),
        ]
    )
    gate, _builder, _store, _doc_id = make_gate(
        client, reviewer, renderer, backend=backend, max_rounds=2
    )

    result = gate.run()

    assert not result.terminated_clean  # the reviewer still had notes at the cap
    assert result.rounds == 2  # but the loop terminated at the cap
    assert renderer.calls == 2  # the last rendered video is the shipped artifact
    assert result.video is not None


def test_the_gate_uses_render_video_while_the_authoring_channel_uses_only_render_still(
    tmp_path: Path,
) -> None:
    backend = CountingBackend()
    renderer = FakeRenderer(backend, tmp_path)
    reviewer = ScriptedReviewer([_blocking("look at the framing"), _CLEAN])
    # the edit round asks for a still to check its work -- the in-loop image channel
    client = ScriptedClient(
        [turn(call("render_still", t=1.0)), turn(call("finish"))]
    )
    gate, _builder, _store, _doc_id = make_gate(client, reviewer, renderer, backend=backend)

    result = gate.run()

    assert result.terminated_clean
    assert backend.video == 2  # full-motion renders come only from the gate
    assert backend.video == renderer.calls  # the authoring loop never triggers render_video
    assert backend.still == 1  # the in-loop vision channel still uses render_still


def test_the_gate_depends_only_on_the_review_agent_interface(tmp_path: Path) -> None:
    # Two different ReviewAgent implementations drive the same gate unchanged (swap seam, story 20).
    for reviewer in (ScriptedReviewer([_CLEAN]), AlwaysCleanReviewer()):
        backend = CountingBackend()
        renderer = FakeRenderer(backend, tmp_path)
        gate, _builder, _store, _doc_id = make_gate(
            ScriptedClient([]), reviewer, renderer, backend=backend
        )

        result = gate.run()

        assert result.terminated_clean and result.video is not None
