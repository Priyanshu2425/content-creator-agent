"""Shared base for ModelClients backed by an OpenAI-compatible chat-completions API.

Many providers (NVIDIA NIM, Perplexity, Together, Groq, ...) expose the OpenAI wire protocol with
only a different ``base_url`` and API key. This module holds the one-time translation between the
loop's neutral history/tool types and that protocol, plus a streaming ``next_turn``; a concrete
provider is then a tiny subclass that sets ``base_url``, ``env_var``, and a default model.

The ``openai`` SDK is an optional dependency, imported lazily: the package and its deterministic
tests load without it, and a clear install hint surfaces only on a real run. A client may be
injected (the test seam) so translation is verified end to end without a key or a network call.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from typing import Any, ClassVar

from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)


def to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _result_text(result: ToolResult) -> str:
    parts: list[str] = []
    if result.text is not None:
        parts.append(result.text)
    if result.images:
        parts.append(
            f"[{len(result.images)} image(s) attached — vision not supported by this provider]"
        )
    return "\n".join(parts)


def to_messages(history: Sequence[HistoryItem]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in history:
        if isinstance(item, UserMessage):
            messages.append({"role": "user", "content": item.text})
        elif isinstance(item, AssistantTurn):
            msg: dict[str, Any] = {"role": "assistant", "content": item.text or ""}
            if item.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.args)},
                    }
                    for call in item.tool_calls
                ]
            messages.append(msg)
        elif isinstance(item, ToolResultsMessage):
            for result in item.results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": _result_text(result),
                    }
                )
    return messages


def collect_stream(stream: Any) -> AssistantTurn:
    """Drain a streaming chat completion (content + tool-call deltas) into an AssistantTurn."""
    text_parts: list[str] = []
    tc_map: dict[int, dict[str, Any]] = {}  # index -> accumulating tool-call fields

    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            text_parts.append(delta.content)
        for tc_delta in getattr(delta, "tool_calls", None) or []:
            idx: int = tc_delta.index
            entry = tc_map.setdefault(idx, {"id": "", "name": "", "args_parts": []})
            if tc_delta.id:
                entry["id"] = tc_delta.id
            fn = getattr(tc_delta, "function", None)
            if fn:
                if getattr(fn, "name", None):
                    entry["name"] = fn.name
                if getattr(fn, "arguments", None):
                    entry["args_parts"].append(fn.arguments)

    calls: list[ToolCall] = []
    for idx in sorted(tc_map):
        entry = tc_map[idx]
        raw_args = "".join(entry["args_parts"])
        args: dict[str, object] = json.loads(raw_args) if raw_args else {}
        calls.append(ToolCall(id=entry["id"], name=entry["name"], args=args))

    return AssistantTurn(tool_calls=tuple(calls), text="".join(text_parts) or None)


class OpenAICompatModelClient:
    """Base ``ModelClient`` for any OpenAI-compatible chat API. Subclasses set the class vars."""

    base_url: ClassVar[str]
    env_var: ClassVar[str]
    provider_label: ClassVar[str]
    # Image ToolResults are stringified to a note (see ``_result_text``), so these clients author
    # blind and get the text-return advisor tool instead (ADR 0007). Inherited by all subclasses.
    consumes_images = False

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 0.95,
        extra_body: dict[str, Any] | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        max_retries: int = 10,
        retry_base_seconds: float = 5.0,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._extra_body = extra_body
        self._client = client if client is not None else self._build_client(api_key)
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds

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
        messages = [{"role": "system", "content": system}, *to_messages(history)]
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            top_p=self._top_p,
            max_tokens=self._max_tokens,
            stream=True,
        )
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        if tools:
            kwargs["tools"] = to_tools(tools)
            kwargs["tool_choice"] = "auto"

        attempt = 0
        while True:
            try:
                stream = self._client.chat.completions.create(**kwargs)
                return collect_stream(stream)
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt >= self._max_retries:
                    raise
                wait = _retry_after(exc) or self._retry_base_seconds * (2 ** attempt)
                attempt += 1
                from videogen import log
                log.get().agent_event_complete(
                    "rate-limit-retry",
                    duration_ms=0,
                    attempt=attempt,
                    wait_seconds=round(wait, 1),
                    model=self._model,
                )
                time.sleep(wait)

    @classmethod
    def _build_client(cls, api_key: str | None) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                f"the {cls.provider_label} adapter needs the openai SDK; install it with "
                f"`uv sync --extra openai` and set {cls.env_var}"
            ) from exc
        key = api_key or os.environ.get(cls.env_var)
        if not key:
            raise RuntimeError(
                f"{cls.env_var} is not set; export it or pass api_key= explicitly"
            )
        return OpenAI(base_url=cls.base_url, api_key=key)


def _is_rate_limit(exc: Exception) -> bool:
    """True for HTTP 429 rate-limit errors from the openai SDK."""
    try:
        from openai import RateLimitError
        return isinstance(exc, RateLimitError)
    except ImportError:
        return getattr(exc, "status_code", None) == 429


def _retry_after(exc: Exception) -> float | None:
    """Extract the provider's suggested retry-after delay (seconds) from a 429, if present.

    Handles two OpenRouter formats:
    - Venice provider: metadata.retry_after_seconds (float)
    - OpenRouter RPM limiter: metadata.headers.X-RateLimit-Reset (epoch milliseconds)
    """
    try:
        body = getattr(exc, "body", None) or {}
        metadata = body.get("error", {}).get("metadata", {}) or {}

        # Format 1: Venice — retry_after_seconds directly in metadata
        seconds = metadata.get("retry_after_seconds")
        if seconds is not None:
            return float(seconds) + 1.0

        # Format 2: OpenRouter RPM limiter — X-RateLimit-Reset as epoch milliseconds
        reset_ms = (metadata.get("headers") or {}).get("X-RateLimit-Reset")
        if reset_ms is not None:
            wait = float(reset_ms) / 1000.0 - time.time()
            return max(wait + 1.0, 1.0)  # at least 1s, plus a 1s buffer
    except Exception:
        pass
    return None
