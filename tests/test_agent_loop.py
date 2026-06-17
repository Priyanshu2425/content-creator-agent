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

from videogen.agent.loop import DirectorLoop
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
        self.tools_seen: list[list[str]] = []  # the tool names offered on each turn

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.calls += 1
        self.seen.append(list(history))
        self.tools_seen.append([t.name for t in tools])
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
    advisor: object | None = None,
    dispatchers: dict | None = None,
    brand_kit: object | None = None,
    max_dispatch_per_worker: int = 2,
) -> tuple[DirectorLoop, Builder, CompositionStore, str]:
    builder = builder or Builder.new(
        voiceover="host",
        duration=2.0,
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
    )
    store = CompositionStore()
    doc_id = store.open(builder.composition)
    loop = DirectorLoop(
        client,  # type: ignore[arg-type]
        builder,
        make_manifest(),
        store,
        doc_id,
        backend=backend,  # type: ignore[arg-type]
        brief="make a short",
        max_ops=max_ops,
        advisor=advisor,  # type: ignore[arg-type]
        dispatchers=dispatchers,  # type: ignore[arg-type]
        brand_kit=brand_kit,
        max_dispatch_per_worker=max_dispatch_per_worker,
    )
    return loop, builder, store, doc_id


class BlindClient(ScriptedClient):
    """A ScriptedClient that cannot consume images -- the trigger for the advisor channel."""

    consumes_images = False


class FakeAdvisor:
    """A VisionAdvisor that records each call and returns canned text advice."""

    def __init__(self, advice: str = "shift the host crop down ~10%") -> None:
        self._advice = advice
        self.calls: list[dict[str, object]] = []

    def advise(self, *, image: bytes, question: str, context: str) -> str:
        self.calls.append({"image": image, "question": question, "context": context})
        return self._advice


def seeded_builder() -> Builder:
    """A gate-clean first pass: one full scene filled with the host, so ``finish`` terminates."""
    builder = Builder.new(
        voiceover="host",
        duration=2.0,
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
    )
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    return builder


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


# --- the advisor / consult_placement channel for image-blind clients (ADR 0007) ---


def test_blind_client_with_advisor_is_offered_consult_placement_and_it_returns_text() -> None:
    client = BlindClient(
        [
            turn(call("consult_placement", t=1.0, question="is the host's face cut off?")),
            turn(call("finish")),
        ]
    )
    backend = CountingBackend()
    advisor = FakeAdvisor("shift the host crop down 10%")
    loop, _builder, store, doc_id = make_loop(
        client, backend=backend, builder=seeded_builder(), advisor=advisor
    )

    result = loop.run()

    assert result.terminated_clean
    offered = client.tools_seen[0]
    assert "consult_placement" in offered  # the text-return vision channel is advertised
    assert "render_still" not in offered and "scene_preview" not in offered  # image tools dropped
    assert backend.still == 1 and backend.video == 0  # advice renders a still, never a video
    assert advisor.calls[0]["question"] == "is the host's face cut off?"
    assert advisor.calls[0]["image"] == b"fake-png"  # the rendered frame reached the advisor
    assert "consult_placement" in [entry.op for entry in store.journal(doc_id)]


def test_sighted_client_keeps_image_vision_tools_and_is_not_offered_the_advisor() -> None:
    client = ScriptedClient([turn(call("finish"))])  # no consumes_images attr -> treated as sighted
    advisor = FakeAdvisor()
    loop, _builder, _store, _doc_id = make_loop(
        client, backend=CountingBackend(), builder=seeded_builder(), advisor=advisor
    )

    loop.run()

    offered = client.tools_seen[0]
    assert "render_still" in offered and "scene_preview" in offered
    assert "consult_placement" not in offered
    assert advisor.calls == []  # a sighted client never consults the advisor


def test_blind_client_without_an_advisor_is_not_offered_consult_placement() -> None:
    client = BlindClient([turn(call("finish"))])
    loop, _builder, _store, _doc_id = make_loop(
        client, backend=CountingBackend(), builder=seeded_builder()  # no advisor injected
    )

    loop.run()

    offered = client.tools_seen[0]
    assert "consult_placement" not in offered  # nothing to delegate to
    assert "render_still" in offered  # falls back to the full TOOLS list unchanged


def test_blind_client_with_advisor_but_no_backend_falls_back_to_plain_tools() -> None:
    client = BlindClient([turn(call("finish"))])
    loop, _builder, _store, _doc_id = make_loop(
        client, backend=None, builder=seeded_builder(), advisor=FakeAdvisor()
    )

    loop.run()

    # no backend means no still to render, so the advice tool can't function -> not offered
    assert "consult_placement" not in client.tools_seen[0]


# --- worker dispatch (restructure/03, ADR 0008) ----------------------------------------------

from videogen.agent.dispatch import NewAsset, WorkerProposal  # noqa: E402


class FakeBrollDispatcher:
    """Stands in for the real b-roll worker: records each call and returns a fixed proposal."""

    def __init__(self, assets: tuple[NewAsset, ...] = ()) -> None:
        self.calls: list[dict] = []
        self._assets = assets

    def __call__(self, guidance: dict) -> WorkerProposal:
        self.calls.append(guidance)
        return WorkerProposal(
            proposal_text="shot list: broll_1 depicts a city skyline",
            new_assets=self._assets,
        )


class FakeBrandKit:
    """Minimal brand kit exposing the tokens() seam the loop injects into a dispatch."""

    def tokens(self) -> dict:
        return {"colors": {"bg": "#000"}, "caption_style": "pill"}


def test_dispatch_broll_tool_is_advertised_only_when_a_worker_is_wired() -> None:
    without = ScriptedClient([turn()])
    loop, *_ = make_loop(without)
    loop.run()
    assert "dispatch_broll" not in without.tools_seen[0]

    with_disp = ScriptedClient([turn()])
    loop, *_ = make_loop(with_disp, dispatchers={"dispatch_broll": FakeBrollDispatcher()})
    loop.run()
    assert "dispatch_broll" in with_disp.tools_seen[0]


def test_dispatch_broll_runs_the_worker_registers_assets_and_threads_the_proposal() -> None:
    new = NewAsset("broll_1", Asset(type=AssetType.image, src="broll_1.png"), "city skyline")
    dispatcher = FakeBrollDispatcher(assets=(new,))
    client = ScriptedClient([turn(call("dispatch_broll", guidance="cover the open")), turn()])
    loop, builder, _store, _doc = make_loop(
        client, dispatchers={"dispatch_broll": dispatcher}, brand_kit=FakeBrandKit()
    )
    loop.run()

    # the worker ran, the brand kit tokens were injected
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["brand_kit"] == {"colors": {"bg": "#000"}, "caption_style": "pill"}
    # the generated asset is registered into the library, ready for fill_region/add_overlay
    assert "broll_1" in builder.composition.assets
    # the proposal text is threaded back to the model on the following turn
    tool_msg = next(m for m in client.seen[1] if isinstance(m, ToolResultsMessage))
    assert "city skyline" in (tool_msg.results[0].text or "")
    assert "broll_1" in (tool_msg.results[0].text or "")


def test_director_can_place_a_dispatched_broll_asset_end_to_end() -> None:
    new = NewAsset("broll_1", Asset(type=AssetType.image, src="broll_1.png"), "city skyline")
    dispatcher = FakeBrollDispatcher(assets=(new,))
    client = ScriptedClient(
        [
            turn(call("dispatch_broll")),
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s1")),
            turn(call("fill_region", scene_id="s1", region="full", asset_id="broll_1")),
            turn(call("finish")),
        ]
    )
    loop, builder, _store, _doc = make_loop(client, dispatchers={"dispatch_broll": dispatcher})
    result = loop.run()

    assert result.terminated_clean
    scene = builder.get_scene("s1")
    assert scene is not None and scene.regions[RegionName.full].asset == "broll_1"


def test_dispatch_budget_is_enforced_per_worker() -> None:
    dispatcher = FakeBrollDispatcher()
    client = ScriptedClient(
        [turn(call("dispatch_broll")), turn(call("dispatch_broll")), turn()]
    )
    loop, *_ = make_loop(
        client, dispatchers={"dispatch_broll": dispatcher}, max_dispatch_per_worker=1
    )
    loop.run()

    # the dispatcher ran once; the second dispatch was refused by the budget
    assert len(dispatcher.calls) == 1
    tool_msg = _last_tool_results(client.seen[2])
    assert "budget exhausted" in (tool_msg.results[0].text or "")


def test_dispatch_does_not_consume_the_builder_op_budget() -> None:
    dispatcher = FakeBrollDispatcher()
    # Two dispatches then finish: with max_ops=1, dispatches must not count or finish never runs.
    client = ScriptedClient(
        [turn(call("dispatch_broll")), turn(call("dispatch_broll")), turn(call("finish"))]
    )
    loop, *_ = make_loop(
        client, dispatchers={"dispatch_broll": dispatcher}, max_ops=1, max_dispatch_per_worker=5
    )
    result = loop.run()

    assert result.terminated_clean
    assert result.ops_used == 1  # only the finish op counted


# --- text-hook dispatch (texthook/02, ADR 0008) -----------------------------------------------


class FakeTextHookDispatcher:
    """Stands in for the text-hook worker: returns a candidates proposal, no assets."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, guidance: dict) -> WorkerProposal:
        self.calls.append(guidance)
        return WorkerProposal(
            proposal_text='Text-hook candidates:\n  1. "Stop scrolling" [curiosity_gap] <- recommended',
            new_assets=(),
        )


def test_dispatch_text_hook_is_advertised_only_when_wired() -> None:
    with_disp = ScriptedClient([turn()])
    loop, *_ = make_loop(with_disp, dispatchers={"dispatch_text_hook": FakeTextHookDispatcher()})
    loop.run()
    assert "dispatch_text_hook" in with_disp.tools_seen[0]


def test_director_dispatches_text_hook_then_places_it_with_add_title() -> None:
    dispatcher = FakeTextHookDispatcher()
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("dispatch_text_hook", guidance="freelancers")),
            turn(call("add_title", text="Stop scrolling", start=0.0, end=2.0, placement="upper-third")),
            turn(call("finish")),
        ]
    )
    loop, builder, _store, _doc = make_loop(
        client, dispatchers={"dispatch_text_hook": dispatcher}
    )
    result = loop.run()

    assert result.terminated_clean
    assert len(dispatcher.calls) == 1
    titles = [o for o in builder.composition.overlays if o.type == "title"]
    assert len(titles) == 1 and titles[0].text == "Stop scrolling"


# --- sfx dispatch (sfx/02, ADR 0009) ----------------------------------------------------------


class FakeSfxDispatcher:
    """Stands in for the SFX worker: returns cut-bound scene_audio placements."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, guidance: dict) -> WorkerProposal:
        self.calls.append(guidance)
        return WorkerProposal(proposal_text="sfx placed", scene_audio=(("s0", "whoosh"),))


def test_dispatch_sfx_applies_scene_audio_and_passes_the_event_timeline() -> None:
    dispatcher = FakeSfxDispatcher()
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("dispatch_sfx")),
            turn(call("finish")),
        ]
    )
    loop, builder, _store, _doc = make_loop(client, dispatchers={"dispatch_sfx": dispatcher})
    result = loop.run()

    assert result.terminated_clean
    scene = builder.get_scene("s0")
    assert scene is not None and scene.audio is not None and scene.audio.sound.value == "whoosh"
    # the Director (loop) built and handed the event timeline to the worker
    assert "event_timeline" in dispatcher.calls[0]
