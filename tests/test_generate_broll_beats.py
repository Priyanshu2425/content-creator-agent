"""GenerateBrollAgent is beat-driven and beat-keyed (ADR 0012, beat-plan/01).

When dispatched with the beats that need visuals, the worker tags each generated asset with the beat
it serves, so the Director binds it by lookup. These tests script a fake ModelClient (one
generate_image call carrying a ``beat`` argument) and a stub image creator, then assert the produced
slot carries that beat_id.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from videogen.agent.beat_plan import AssetSpec, Beat
from videogen.agent.generate_broll import GenerateBrollAgent
from videogen.agent.model import AssistantTurn, HistoryItem, ToolCall, ToolSpec
from videogen.agent.perception import AssetFact, MediaManifest


class _Word:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


class _Transcript:
    def __init__(self, words: list[_Word]) -> None:
        self.words = words

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _manifest() -> MediaManifest:
    return MediaManifest(
        assets=(AssetFact("host", "video", "host.mp4", 2.0, 1080, 1920),),
        voiceover="host",
        duration=2.0,
        fps=30.0,
        transcript=_Transcript([_Word("ship", 0.0, 1.0), _Word("faster", 1.0, 2.0)]),
    )


class _ScriptedClient:
    """Emits one generate_image call (bound to beat b1), then stops."""

    model = "fake"

    def __init__(self) -> None:
        self._turns = [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="generate_image",
                        args={"slot": 1, "beat": "b1", "prompt": "a rocket", "aspect_ratio": "9:16"},
                    ),
                )
            ),
            AssistantTurn(),
        ]

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        return self._turns.pop(0) if self._turns else AssistantTurn()


class _StubCreator:
    """Writes a placeholder PNG so the agent records a successful slot."""

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str = "9:16") -> Path:
        out_path.write_bytes(b"fake-png")
        return out_path


def test_run_tags_the_generated_slot_with_its_beat_id(tmp_path: Path) -> None:
    agent = GenerateBrollAgent(_ScriptedClient(), _StubCreator())  # type: ignore[arg-type]
    beats = [
        Beat(
            id="b1",
            transcript_span=(0, 1),
            role="climax",
            intent="the payoff",
            asset_spec=AssetSpec(kind="broll-image", brief="a rocket launching"),
        )
    ]

    result = agent.run(
        _manifest(), "brief", "Instagram", "", dest=tmp_path, beats=beats
    )

    assert len(result.slots) == 1
    assert result.slots[0].beat_id == "b1"
