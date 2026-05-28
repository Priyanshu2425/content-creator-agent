"""ClaudeCodeClient: authoring ModelClient over the Claude Code CLI (claude-agent-sdk, ADR 0006).

The SDK call and the CLI auth are external, so these tests cover the part that is ours and
deterministic: hiding the vision tools, folding the JSON output contract into the system prompt,
serializing the neutral history into a single replay prompt, and tolerantly parsing the model's
JSON tool call back into a neutral ``AssistantTurn``. ``next_turn`` is driven against a fake async
query seam (a recorder) so the round trip is verified without the SDK, a CLI, or a network call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from videogen.agent.clients.claude_code import (
    ClaudeCodeClient,
    _extract_json,
    _parse_turn,
    _render_prompt,
    _system_with_contract,
    _visible_tools,
)
from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from videogen.agent.tools import TOOLS, VISION_OPS


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"the {name} tool", input_schema={"type": "object"})


def test_visible_tools_hides_the_vision_tools_and_keeps_the_rest() -> None:
    names = {t.name for t in _visible_tools(TOOLS)}

    assert names.isdisjoint(VISION_OPS)  # render_still / scene_preview are gone
    assert "add_scene" in names and "finish" in names  # authoring + terminal tools remain


def test_system_with_contract_embeds_the_tool_catalog_and_the_json_only_rule() -> None:
    system = _system_with_contract("AUTHOR SYSTEM", [_spec("add_scene"), _spec("finish")])

    assert system.startswith("AUTHOR SYSTEM")
    assert '"name": "add_scene"' in system  # the catalog is serialized in
    assert '{"name": "<tool name>", "args": { ...arguments... }}' in system  # the output contract
    assert '{"name": "finish", "args": {}}' in system  # how to terminate


def test_render_prompt_replays_history_drops_images_and_asks_for_the_next_call() -> None:
    history: list[HistoryItem] = [
        UserMessage(text="Brief: a 2s short\n\nPERCEPTION..."),
        AssistantTurn(
            text="adding a scene",
            tool_calls=(ToolCall(id="c1", name="add_scene", args={"start": 0.0}),),
        ),
        ToolResultsMessage(
            results=(ToolResult(call_id="c1", text="validation: PASS", images=(b"png",)),)
        ),
    ]

    prompt = _render_prompt(history)

    assert "Brief: a 2s short" in prompt
    assert "you called add_scene" in prompt and '{"start": 0.0}' in prompt
    assert "Result: validation: PASS" in prompt
    assert "1 image(s) omitted" in prompt  # no image channel: dropped with a note
    assert prompt.rstrip().endswith("emit the next single tool call as a JSON object.")


def test_extract_json_tolerates_fences_and_trailing_prose() -> None:
    assert _extract_json('{"name": "finish", "args": {}}') == {"name": "finish", "args": {}}
    fenced = '```json\n{"name": "add_scene", "args": {"start": 0}}\n```'
    assert _extract_json(fenced) == {"name": "add_scene", "args": {"start": 0}}
    chatty = 'Sure! Here it is:\n{"name": "finish", "args": {}}\nLet me know if that works.'
    assert _extract_json(chatty) == {"name": "finish", "args": {}}
    assert _extract_json("no json here at all") is None


def test_parse_turn_builds_a_single_tool_call_and_assigns_an_id() -> None:
    turn = _parse_turn('{"name": "fill_region", "args": {"region": "full"}}')

    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert call.name == "fill_region" and call.args == {"region": "full"}
    assert call.id  # an id is synthesized (the SDK has no native tool-call id here)


def test_parse_turn_returns_an_empty_turn_when_the_reply_is_not_a_tool_call() -> None:
    # ADR 0006: a hard parse failure ends the turn with no call -- the loop then stops cleanly.
    assert _parse_turn("I think we're done here.") == AssistantTurn()
    assert _parse_turn('{"args": {}}') == AssistantTurn()  # missing name


def test_next_turn_drives_the_query_seam_and_parses_the_reply() -> None:
    class _Recorder:
        def __init__(self, reply: str) -> None:
            self._reply = reply
            self.seen: dict[str, Any] = {}

        async def __call__(self, *, prompt: str, system: str, model: str | None) -> Any:
            self.seen = {"prompt": prompt, "system": system, "model": model}
            yield SimpleNamespace(content=[SimpleNamespace(text=self._reply)])

    recorder = _Recorder('{"name": "finish", "args": {}}')
    client = ClaudeCodeClient(model="claude-opus-4-7", query_fn=recorder)

    turn = client.next_turn(
        system="you author videos",
        history=[UserMessage(text="go")],
        tools=TOOLS,
    )

    assert turn.tool_calls and turn.tool_calls[0].name == "finish"
    # the vision tools never reach the model, and the JSON contract is folded into the system prompt
    assert "render_still" not in recorder.seen["system"]
    assert '{"name": "<tool name>"' in recorder.seen["system"]
    assert "go" in recorder.seen["prompt"]
    assert recorder.seen["model"] == "claude-opus-4-7"
