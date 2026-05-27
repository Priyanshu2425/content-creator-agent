"""AuthoringService: Manifest + brief -> finished, validated Composition (Phase 8, ADR 0003/0004).

The service is the host of the authoring agent and the producer of the Composition. These tests
assert its external contract with a stubbed model: seeded from the Media Manifest's facts, it drives
the loop to a Composition that passes the submit-render gate, and it returns a reconstructable audit
journal of the ops the agent applied. They also pin the ADR 0003 boundary -- the service imports the
kernel, the agent module, and the backend *seam*, never a concrete render engine.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from pathlib import Path

from videogen.agent.model import AssistantTurn, HistoryItem, ToolCall, ToolSpec
from videogen.agent.perception import AssetFact, MediaManifest
from videogen.kernel.composition import AssetType
from videogen.kernel.ir import IR
from videogen.kernel.validator import can_submit_render
from videogen.services.authoring import AuthoringService

_ids = itertools.count()


def call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=f"c{next(_ids)}", name=name, args=args)


def turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(tool_calls=calls)


class ScriptedClient:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        return self._turns.pop(0) if self._turns else AssistantTurn()


class _NullBackend:
    def render_video(self, ir: IR, out_path: Path) -> Path:  # pragma: no cover - unused
        return out_path

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:  # pragma: no cover - unused
        out_path.write_bytes(b"png")
        return out_path


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


def test_author_returns_a_gate_passing_composition_seeded_from_the_manifest() -> None:
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("add_captions_from_transcript", style="pill")),
            turn(call("finish")),
        ]
    )
    service = AuthoringService(backend=_NullBackend())

    result = service.author(make_manifest(), "a 2s talking-head short", model_client=client)

    assert result.terminated_clean
    assert can_submit_render(result.composition, duration=2.0)  # the gate the render step enforces
    # seeded from the manifest's objective facts (not authored by the agent)
    assert result.composition.voiceover.asset == "host"
    assert result.composition.assets["host"].type is AssetType.video
    assert result.composition.scenes[0].id == "s0"


def test_author_returns_a_reconstructable_audit_journal() -> None:
    client = ScriptedClient(
        [
            turn(call("add_scene", layout="full", start=0.0, end=2.0, id="s0")),
            turn(call("fill_region", scene_id="s0", region="full", asset_id="host")),
            turn(call("finish")),
        ]
    )
    service = AuthoringService(backend=_NullBackend())

    result = service.author(make_manifest(), "brief", model_client=client)

    assert [entry.op for entry in result.journal] == ["add_scene", "fill_region"]


def test_service_does_not_depend_on_a_concrete_render_engine() -> None:
    """ADR 0003: AuthoringService depends on the kernel, the agent module, and the backend seam --
    never on Remotion or RenderService internals."""
    source = Path("src/videogen/services/authoring.py").read_text()
    assert "backends.remotion" not in source
    assert "services.render" not in source
