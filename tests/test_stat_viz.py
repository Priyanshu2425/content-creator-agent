"""StatVizRenderer and GenerateBrollAgent stat-viz dispatch tests.

StatVizRenderer: stub RemotionBackend.render_clip to assert composition id selection and prop
merging without shelling out to Node. GenerateBrollAgent dispatch: use a scripted ModelClient
(same pattern as test_agent_loop) to emit render_* tool calls and assert GeneratedSlot shape,
error recovery, and image-only mode when stat_viz_renderer=None.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest

from videogen.agent.generate_broll import GenerateBrollAgent, GeneratedSlot
from videogen.agent.model import AssistantTurn, HistoryItem, ToolCall, ToolResult, ToolSpec
from videogen.agent.perception import AssetFact, MediaManifest
from videogen.agent.stat_viz import DEFAULT_STYLE_BRIEF, StyleBrief, StatVizRenderer
from videogen.services.media import Transcript, Word


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Records render_clip calls; writes an empty file to out_path so existence checks pass."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def render_clip(self, composition_id: str, props: dict[str, Any], out_path: Path) -> Path:
        self.calls.append({"composition_id": composition_id, "props": props, "out_path": out_path})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-mp4")
        return out_path


class _FakeCreator:
    """NanoBananaCreator stub: writes empty PNG bytes."""

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-png")
        return out_path


class _ScriptedClient:
    """Emits a fixed sequence of AssistantTurns; records the tool names offered each call."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self.tools_seen: list[list[str]] = []

    def next_turn(
        self, *, system: str, history: Sequence[HistoryItem], tools: Sequence[ToolSpec]
    ) -> AssistantTurn:
        self.tools_seen.append([t.name for t in tools])
        return self._turns.pop(0) if self._turns else AssistantTurn()


_ids = (f"c{i}" for i in range(10_000))


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=next(_ids), name=name, args=args)


def _manifest() -> MediaManifest:
    return MediaManifest(
        assets=(AssetFact(id="host", type="video", source="host.mp4"),),
        voiceover="host",
        duration=10.0,
        fps=30.0,
        transcript=Transcript(words=[Word(text="hello", start=0.0, end=1.0)]),
    )


# ---------------------------------------------------------------------------
# StatVizRenderer unit tests
# ---------------------------------------------------------------------------


def test_stat_viz_renderer_counter_uses_correct_composition_id(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    out = tmp_path / "out.mp4"

    renderer.render("counter", {"value": 40, "unit": "%", "label": "Growth", "duration_s": 2.0}, DEFAULT_STYLE_BRIEF, out)

    assert len(backend.calls) == 1
    assert backend.calls[0]["composition_id"] == "StatVizCounter"


def test_stat_viz_renderer_merges_style_brief_into_props(tmp_path: Path) -> None:
    backend = _FakeBackend()
    style = StyleBrief(background="#111", primary="#fff", accent="#f00", font_family="Helvetica")
    renderer = StatVizRenderer(backend=backend)

    renderer.render("counter", {"value": 10, "unit": "x", "label": "Speed", "duration_s": 1.5}, style, tmp_path / "out.mp4")

    props = backend.calls[0]["props"]
    assert props["background"] == "#111"
    assert props["primary"] == "#fff"
    assert props["accent"] == "#f00"
    assert props["fontFamily"] == "Helvetica"


def test_stat_viz_renderer_data_params_pass_through(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)

    renderer.render("bar", {"label_a": "A", "value_a": 80, "label_b": "B", "value_b": 20, "unit": "%", "duration_s": 2.0}, DEFAULT_STYLE_BRIEF, tmp_path / "out.mp4")

    props = backend.calls[0]["props"]
    assert props["value_a"] == 80
    assert props["value_b"] == 20
    assert props["label_a"] == "A"


@pytest.mark.parametrize("format_name, expected_id", [
    ("counter", "StatVizCounter"),
    ("bar", "StatVizBar"),
    ("gauge", "StatVizGauge"),
    ("before_after", "StatVizBeforeAfter"),
    ("ratio", "StatVizRatio"),
])
def test_stat_viz_renderer_maps_every_format(tmp_path: Path, format_name: str, expected_id: str) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    data: dict[str, Any] = {"duration_s": 2.0, "label": "test", "value": 1, "max": 10,
                             "unit": "%", "label_a": "A", "value_a": 1, "label_b": "B",
                             "value_b": 2, "value_a": "old", "value_b": "new",
                             "numerator": 1, "denominator": 3}

    renderer.render(format_name, data, DEFAULT_STYLE_BRIEF, tmp_path / "out.mp4")  # type: ignore[arg-type]

    assert backend.calls[0]["composition_id"] == expected_id


def test_stat_viz_renderer_raises_on_unsupported_format(tmp_path: Path) -> None:
    renderer = StatVizRenderer(backend=_FakeBackend())

    with pytest.raises(ValueError, match="unsupported stat-viz format"):
        renderer.render("scatter", {}, DEFAULT_STYLE_BRIEF, tmp_path / "out.mp4")  # type: ignore[arg-type]


def test_stat_viz_renderer_returns_out_path(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    out = tmp_path / "clip.mp4"

    result = renderer.render("counter", {"value": 1, "unit": "%", "label": "X", "duration_s": 1.0}, DEFAULT_STYLE_BRIEF, out)

    assert result == out


# ---------------------------------------------------------------------------
# GenerateBrollAgent stat-viz dispatch tests
# ---------------------------------------------------------------------------


def test_generate_broll_agent_render_counter_returns_video_slot(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    client = _ScriptedClient([
        AssistantTurn(tool_calls=(_call("render_counter", slot=1, value=40, unit="%", label="Growth", duration_s=2.0),)),
    ])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=renderer)

    result = agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    assert len(result.slots) == 1
    slot = result.slots[0]
    assert slot.kind == "video"
    assert slot.slot_index == 1
    assert slot.path.suffix == ".mp4"
    assert slot.path.exists()


def test_generate_broll_agent_slot_field_not_in_renderer_data(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    client = _ScriptedClient([
        AssistantTurn(tool_calls=(_call("render_counter", slot=2, value=10, unit="x", label="Speed", duration_s=1.5),)),
    ])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=renderer)

    agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    props = backend.calls[0]["props"]
    assert "slot" not in props
    assert props["value"] == 10


def test_generate_broll_agent_render_failure_returns_error_no_slot(tmp_path: Path) -> None:
    class _BrokenBackend:
        def render_clip(self, *_args: Any, **_kwargs: Any) -> Path:
            raise RuntimeError("render failed")

    renderer = StatVizRenderer(backend=_BrokenBackend())
    client = _ScriptedClient([
        AssistantTurn(tool_calls=(_call("render_counter", slot=1, value=40, unit="%", label="X", duration_s=2.0),)),
    ])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=renderer)

    result = agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    assert result.slots == ()


def test_generate_broll_agent_without_renderer_omits_stat_viz_tools(tmp_path: Path) -> None:
    client = _ScriptedClient([AssistantTurn()])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=None)

    agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    offered = client.tools_seen[0]
    assert "generate_image" in offered
    assert "render_counter" not in offered
    assert "render_bar" not in offered
    assert "render_gauge" not in offered
    assert "render_before_after" not in offered
    assert "render_ratio" not in offered


def test_generate_broll_agent_with_renderer_includes_all_stat_viz_tools(tmp_path: Path) -> None:
    renderer = StatVizRenderer(backend=_FakeBackend())
    client = _ScriptedClient([AssistantTurn()])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=renderer)

    agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    offered = client.tools_seen[0]
    for name in ("generate_image", "render_counter", "render_bar", "render_gauge", "render_before_after", "render_ratio"):
        assert name in offered


def test_generate_broll_agent_image_and_video_slots_in_same_turn(tmp_path: Path) -> None:
    backend = _FakeBackend()
    renderer = StatVizRenderer(backend=backend)
    client = _ScriptedClient([
        AssistantTurn(tool_calls=(
            _call("generate_image", slot=1, prompt="cityscape", aspect_ratio="9:16"),
            _call("render_counter", slot=2, value=40, unit="%", label="Growth", duration_s=2.0),
        )),
    ])
    agent = GenerateBrollAgent(client, _FakeCreator(), stat_viz_renderer=renderer)

    result = agent.run(manifest=_manifest(), brief="test", platform="Instagram", ideal_cuts_plan="", dest=tmp_path)

    assert len(result.slots) == 2
    kinds = {s.kind for s in result.slots}
    assert kinds == {"image", "video"}
