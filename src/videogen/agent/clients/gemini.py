"""GeminiModelClient: ModelClient adapter over the Gemini API (google-genai SDK).

Same provider-agnostic pattern as AnthropicModelClient: translates the loop's neutral
history/tool types into Gemini Contents/Parts wire format and parses the response back into a
neutral AssistantTurn. The google-genai SDK is already an optional dependency (used by
GeminiReviewAgent); the install hint surfaces only on a real run.

Requires GEMINI_API_KEY or GOOGLE_API_KEY in the environment.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ToolCall,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)

_DEFAULT_MODEL = "gemini-2.5-flash"


def _to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    if not tools:
        return []
    return [
        {
            "function_declarations": [
                {"name": t.name, "description": t.description, "parameters": t.input_schema}
                for t in tools
            ]
        }
    ]


def _to_contents(history: Sequence[HistoryItem]) -> list[dict[str, Any]]:
    # Build call_id -> function_name so ToolResultsMessage can emit the right function_response name
    id_to_name: dict[str, str] = {}
    for item in history:
        if isinstance(item, AssistantTurn):
            for call in item.tool_calls:
                id_to_name[call.id] = call.name

    contents: list[dict[str, Any]] = []
    for item in history:
        if isinstance(item, UserMessage):
            parts: list[dict[str, Any]] = [{"text": item.text}]
            for img_bytes in item.images:
                import base64
                mime = "image/jpeg" if img_bytes[:3] == b"\xff\xd8\xff" else "image/png"
                parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(img_bytes).decode()}})
            contents.append({"role": "user", "parts": parts})
        elif isinstance(item, AssistantTurn):
            parts: list[dict[str, Any]] = []
            if item.text:
                parts.append({"text": item.text})
            for call in item.tool_calls:
                parts.append({"function_call": {"name": call.name, "args": dict(call.args)}})
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif isinstance(item, ToolResultsMessage):
            parts = []
            for result in item.results:
                fn_name = id_to_name.get(result.call_id, result.call_id)
                text = result.text or ""
                if result.images:
                    text += f"\n[{len(result.images)} image(s) attached; vision not in history]"
                parts.append({"function_response": {"name": fn_name, "response": {"result": text}}})
            if parts:
                contents.append({"role": "user", "parts": parts})
    return contents


def _parse_response(response: Any) -> AssistantTurn:
    texts: list[str] = []
    calls: list[ToolCall] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return AssistantTurn()
    for part in getattr(candidates[0].content, "parts", None) or []:
        if getattr(part, "text", None):
            texts.append(part.text)
        fc = getattr(part, "function_call", None)
        if fc is not None and getattr(fc, "name", None):
            calls.append(ToolCall(
                id=str(uuid.uuid4())[:8],
                name=fc.name,
                args=dict(fc.args) if fc.args else {},
            ))
    return AssistantTurn(
        tool_calls=tuple(calls),
        text="\n".join(texts) or None,
    )


class GeminiModelClient:
    """A ModelClient that drives the authoring loop with a real Gemini model."""

    # This adapter stringifies image ToolResults (vision not carried over this seam), so as an
    # authoring client it is blind and gets the text-return advisor tool instead (ADR 0007).
    consumes_images = False

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
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

        config: dict[str, Any] = {"system_instruction": system}
        tool_list = _to_tools(tools)
        if tool_list:
            config["tools"] = tool_list
        t0 = time.monotonic()
        response = self._client.models.generate_content(
            model=self._model,
            contents=_to_contents(history),
            config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        log.get().llm_call(
            agent="GeminiModelClient",
            model=self._model,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return _parse_response(response)


def _build_client(api_key: str | None) -> Any:
    from videogen.genai_client import build_genai_client

    return build_genai_client(
        api_key,
        install_hint=(
            "the authoring model needs the google-genai SDK; install it with `uv sync --extra review`, then authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or an API key"
        ),
    )
