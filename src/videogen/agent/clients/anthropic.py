"""AnthropicModelClient: the authoring loop's ModelClient over the Anthropic Messages API (Phase 9).

Phase 8 built the loop against the provider-agnostic ``ModelClient`` seam and deferred the real
adapter; this is it. The only job here is translation -- the loop's neutral history/tool types in
one direction, the Messages API ``tool_use``/``tool_result`` wire shapes in the other, and the
model's reply parsed back into a neutral ``AssistantTurn``. Nothing above this module knows the
provider exists, so swapping it for another vendor's adapter is a one-file change.

The ``anthropic`` SDK is an optional dependency, imported lazily (like faster-whisper): the package
and its deterministic tests load without it, and a clear install hint surfaces only when a real run
needs it. An SDK client may be injected (the test seam) so the translation is verified end to end
without a key or a network call.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Sequence
from typing import Any

from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)

# A capable, cost-sensible default for a many-turn agentic loop; override per run if a stronger or
# cheaper model is wanted. The adapter does not depend on the choice.
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 4096


def _to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Render the neutral tool specs as Messages API tool definitions."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _result_content(result: ToolResult) -> list[dict[str, Any]]:
    """The blocks for one tool result: its perception text and/or its vision PNGs."""
    blocks: list[dict[str, Any]] = []
    if result.text is not None:
        blocks.append({"type": "text", "text": result.text})
    for image in result.images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(image).decode("ascii"),
                },
            }
        )
    return blocks


def _to_messages(history: Sequence[HistoryItem]) -> list[dict[str, Any]]:
    """Translate the running neutral history into the Messages API ``messages`` list."""
    messages: list[dict[str, Any]] = []
    for item in history:
        if isinstance(item, UserMessage):
            messages.append({"role": "user", "content": [{"type": "text", "text": item.text}]})
        elif isinstance(item, AssistantTurn):
            content: list[dict[str, Any]] = []
            if item.text:
                content.append({"type": "text", "text": item.text})
            for call in item.tool_calls:
                content.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
                )
            messages.append({"role": "assistant", "content": content})
        elif isinstance(item, ToolResultsMessage):
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": result.call_id,
                    "content": _result_content(result),
                }
                for result in item.results
            ]
            messages.append({"role": "user", "content": blocks})
    return messages


def _parse_response(message: Any) -> AssistantTurn:
    """Pull narration and tool calls off a Messages API reply into a neutral ``AssistantTurn``."""
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in message.content:
        kind = getattr(block, "type", None)
        if kind == "text":
            texts.append(block.text)
        elif kind == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input or {})))
    return AssistantTurn(tool_calls=tuple(calls), text="\n".join(texts) or None)


class AnthropicModelClient:
    """A ``ModelClient`` that drives the authoring loop with a real Anthropic model."""

    consumes_images = True  # the Messages API sends image blocks; this client truly sees stills

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = client if client is not None else _build_client(api_key)

    @property
    def model(self) -> str:
        return self._model

    def next_turn(
        self,
        *,
        system: str,
        history: Sequence[HistoryItem],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        from videogen import log

        t0 = time.monotonic()
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            tools=_to_tools(tools),
            messages=_to_messages(history),
        )
        log.get().llm_call(
            agent="AnthropicModelClient",
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return _parse_response(message)


def _build_client(api_key: str | None) -> Any:
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # optional dependency
        raise RuntimeError(
            "the authoring model needs the anthropic SDK; install it with "
            "`uv sync --extra authoring` and set ANTHROPIC_API_KEY"
        ) from exc
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
