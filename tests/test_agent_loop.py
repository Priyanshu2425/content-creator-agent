"""Authoring loop: tool-use cycle, immediate validation, the finish gate, vision routing (Phase 8).

The model is non-deterministic, so these tests target the *contracts around it*: a scripted
``ModelClient`` emits a fixed sequence of tool calls and the tests assert the loop's externally
observable behavior -- it validates after each op and feeds errors back so the agent can recover,
it refuses to finish while hard errors remain and terminates once the gate is clean, the operation
budget bounds a runaway agent, and the in-loop vision tools route through the backend's render_still
(single frame / sampled strip) and never render_video, only when the agent asks. No live model.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from pathlib import Path

from videogen.agent.loop import AuthoringLoop
from videogen.agent.model import AssistantTurn, HistoryItem, ToolCall, ToolResultsMessage, ToolSpec
from videogen.agent.perception import AssetFact, MediaManifest
from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Composition,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)
from videogen.kernel.ir import IR
from videogen.stores.composition_store import CompositionStore

_ids = itertools.count()


def call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=f"c{next(_ids)}", name=name, args=args)


def turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(tool_calls=calls)


class ScriptedClient:
    """Emits a fixed sequence of turns; records the history it was handed each call."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self.calls = 0
        self.seen: list[list[HistoryItem]] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.calls += 1
        self.seen.append(list(history))
        return self._turns.pop(0) if self._turns else AssistantTurn()


class AlwaysClient:
    """Never finishes: returns the same turn every call (a runaway agent)."""

    def __init__(self, every: AssistantTurn) -> None:
        self._every = every
        self.calls = 0

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.calls += 1
        return self._every


class CountingBackend:
    """A RenderBackend that counts each render path (vision must use only stills, never video)."""

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


class _Word:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


class _Transcript:
    def __init__(self, words: list[_Word]) -> None:
        self.words = words


TRANSCRIPT = _Transcript([_Word("hello", 0.1, 0.5), _Word("world", 0.6, 1.0)])


def make_manifest() -> MediaManifest:
    return MediaManifest(
        assets=(AssetFact("host", "video", "host.mp4", 2.0, 1080, 1920),),
        voiceover="host",
        duration=2.0,
        fps=30.0,
        transcript=TRANSCRIPT,
    )


def make_loop(
    client: object,
    *,
    backend: object | None = None,
    builder: Builder | None = None,
    max_ops: int = 40,
) -> tuple[AuthoringLoop, Builder, CompositionStore, str]:
    builder = builder or Builder.new(
        voiceover="host",
        duration=2.0,
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
    )
    store = CompositionStore()
    doc_id = store.open(builder.composition)
    loop = AuthoringLoop(
        client,  # type: ignore[arg-type]
        builder,
        make_manifest(),
        store,
        doc_id,
        backend=backend,  # type: ignore[arg-type]
        brief="make a short",
        max_ops=max_ops,
    )
    return loop, builder, store, doc_id


def _last_tool_results(history: list[HistoryItem]) -> ToolResultsMessage:
    return next(item for item in reversed(history) if isinstance(item, ToolResultsMessage))


def test_a_clean_script_authors_to_a_gate_passing_composition_and_journals_each_op() -> None:
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("add_captions_from_transcript", style="pill")),
            turn(call("finish")),
        ]
    )
    loop, builder, store, doc_id = make_loop(client, backend=CountingBackend())

    result = loop.run()

    assert result.terminated_clean
    assert builder.can_submit_render()
    assert result.composition.scenes[0].id == "s0"
    assert [e.op for e in store.journal(doc_id)] == [
        "add_scene",
        "fill_region",
        "add_captions_from_transcript",
    ]


def test_an_invalid_op_is_fed_back_and_the_agent_recovers() -> None:
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=5.0)),  # end > 2.0 voiceover
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),  # corrected
            turn(call("finish")),
        ]
    )
    loop, builder, store, doc_id = make_loop(client, backend=CountingBackend())

    result = loop.run()

    # the error from the rejected op was returned as the tool result the agent saw next turn
    fed_back = _last_tool_results(client.seen[1])
    assert any(
        r.text and "scene_out_of_bounds" in r.text for r in fed_back.results
    )
    assert result.terminated_clean
    assert result.composition.scenes[0].end == 2.0  # the corrected scene
    journal = [e.op for e in store.journal(doc_id)]
    assert "add_scene[rejected]" in journal and journal[-1] == "add_scene"


def test_finish_does_not_terminate_while_hard_errors_remain() -> None:
    # A builder whose document already has a hard error (a scene past the voiceover). Builder ops
    # stay clean, so the gate is exercised by starting from an invalid document.
    bad = Composition(
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
        voiceover=Audio(asset="host"),
        scenes=[
            Scene(
                id="s0",
                start=0.0,
                end=5.0,
                layout=LayoutName.full,
                regions={RegionName.full: Ref(asset="host")},
            )
        ],
    )
    client = ScriptedClient([turn(call("finish")), turn(call("finish"))])
    loop, builder, store, doc_id = make_loop(
        client, backend=CountingBackend(), builder=Builder(bad, duration=2.0)
    )

    result = loop.run()

    assert not result.terminated_clean  # the gate refused every finish
    fed_back = _last_tool_results(client.seen[1])
    assert any(r.text and "scene_out_of_bounds" in r.text for r in fed_back.results)


def test_the_operation_budget_bounds_a_runaway_agent() -> None:
    client = AlwaysClient(turn(call("add_caption", text="x", start=0.1, end=0.2, style="pill")))
    loop, builder, store, doc_id = make_loop(client, backend=CountingBackend(), max_ops=3)

    result = loop.run()

    assert not result.terminated_clean
    assert result.ops_used == 3  # stopped at the budget, did not loop forever
    assert len(builder.composition.captions) == 3


def test_vision_tools_route_through_render_still_only_and_only_when_asked() -> None:
    backend = CountingBackend()
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("render_still", t=1.0)),
            turn(call("scene_preview", scene_id="s0")),
            turn(call("finish")),
        ]
    )
    loop, builder, store, doc_id = make_loop(client, backend=backend)

    result = loop.run()

    assert result.terminated_clean
    assert backend.video == 0  # full-motion render is never triggered in the loop
    assert backend.still >= 2  # one still + several preview samples
    journal = [e.op for e in store.journal(doc_id)]
    assert "render_still" in journal and "scene_preview" in journal


def test_system_prompt_carries_vocabulary_and_the_loop_contract() -> None:
    from videogen.agent.prompts import SYSTEM_PROMPT

    for term in ("Composition", "Scene", "Overlay", "Caption", "Voiceover", "Region", "Layout",
                 "Transition"):
        assert term in SYSTEM_PROMPT
    assert "one" in SYSTEM_PROMPT.lower()  # one op per turn
    assert "finish" in SYSTEM_PROMPT
