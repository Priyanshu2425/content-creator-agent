"""AnthropicModelClient: the real ModelClient over the Anthropic Messages API (Phase 9).

The network call is gated behind an API key and the SDK, so these tests cover the part that is
ours and deterministic: the translation between the loop's neutral message/tool types and the
Messages API wire shapes, in both directions. ``next_turn`` is exercised against a fake SDK client
(a recorder) so the translation is verified end to end without a key or a real request.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

from videogen.agent.clients.anthropic import (
    AnthropicModelClient,
    _parse_response,
    _to_messages,
    _to_tools,
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


def test_to_tools_maps_each_spec_to_the_messages_api_shape() -> None:
    schema: dict[str, object] = {"type": "object", "properties": {"t": {"type": "number"}}}
    spec = ToolSpec(name="render_still", description="see a frame", input_schema=schema)
    tools = _to_tools([spec])

    assert tools == [
        {"name": "render_still", "description": "see a frame", "input_schema": schema}
    ]


def test_to_messages_translates_a_full_neutral_history_round_trip() -> None:
    png = b"\x89PNGfake"
    history: list[HistoryItem] = [
        UserMessage(text="the brief + perception"),
        AssistantTurn(
            text="adding a scene",
            tool_calls=(ToolCall(id="c1", name="add_scene", args={"start": 0.0}),),
        ),
        ToolResultsMessage(
            results=(ToolResult(call_id="c1", text="validation: PASS", images=(png,)),)
        ),
    ]

    messages = _to_messages(history)

    assert messages[0] == {
        "role": "user",
        "content": [{"type": "text", "text": "the brief + perception"}],
    }

    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert {"type": "text", "text": "adding a scene"} in assistant["content"]
    tool_use = next(b for b in assistant["content"] if b["type"] == "tool_use")
    assert tool_use == {
        "type": "tool_use", "id": "c1", "name": "add_scene", "input": {"start": 0.0}
    }

    result_msg = messages[2]
    assert result_msg["role"] == "user"
    block = result_msg["content"][0]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "c1"
    text_block = next(b for b in block["content"] if b["type"] == "text")
    assert text_block["text"] == "validation: PASS"
    image_block = next(b for b in block["content"] if b["type"] == "image")
    assert base64.standard_b64decode(image_block["source"]["data"]) == png
    assert image_block["source"]["media_type"] == "image/png"


def test_parse_response_pulls_tool_calls_and_narration_off_the_message() -> None:
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="I'll fill the region"),
            SimpleNamespace(type="tool_use", id="c9", name="fill_region", input={"region": "full"}),
        ]
    )

    turn = _parse_response(message)

    assert turn.text == "I'll fill the region"
    assert turn.tool_calls == (ToolCall(id="c9", name="fill_region", args={"region": "full"}),)


def test_parse_response_with_no_tool_use_yields_an_empty_turn() -> None:
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])

    turn = _parse_response(message)

    assert turn.tool_calls == () and turn.text == "done"


def test_next_turn_calls_the_sdk_with_the_translated_request_and_parses_the_reply() -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs: Any) -> Any:
            self.kwargs = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", id="c1", name="finish", input={})]
            )

    recorder = _Recorder()
    client = AnthropicModelClient(model="claude-sonnet-4-6", client=recorder)

    turn = client.next_turn(
        system="you author videos",
        history=[UserMessage(text="go")],
        tools=[ToolSpec(name="finish", description="stop", input_schema={"type": "object"})],
    )

    assert turn.tool_calls == (ToolCall(id="c1", name="finish", args={}),)
    assert recorder.kwargs["model"] == "claude-sonnet-4-6"
    assert recorder.kwargs["system"] == "you author videos"
    assert recorder.kwargs["tools"][0]["name"] == "finish"
    assert recorder.kwargs["messages"][0]["role"] == "user"
