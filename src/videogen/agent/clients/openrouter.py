"""OpenRouterModelClient: ModelClient over OpenRouter's OpenAI-compatible API.

A thin subclass of OpenAICompatModelClient: sets OpenRouter's base URL and the OPENROUTER_API_KEY
env var. All wire translation lives in the shared base. OpenRouter routes to many model providers
(Anthropic, Google, Meta, Mistral, …) so the model string is the provider/model slug from
openrouter.ai, e.g. ``anthropic/claude-sonnet-4-6`` or ``google/gemini-2.5-pro``.

Optional headers (``HTTP-Referer`` / ``X-Title``) can be passed via ``extra_headers`` for OpenRouter
analytics; omit them and they default to nothing.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from videogen.agent.clients._openai_compat import OpenAICompatModelClient, collect_stream, to_messages, to_tools
from videogen.agent.model import AssistantTurn, HistoryItem, ToolSpec

_DEFAULT_MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"


class OpenRouterModelClient(OpenAICompatModelClient):
    """A ``ModelClient`` that drives the authoring loop via OpenRouter."""

    base_url = "https://openrouter.ai/api/v1"
    env_var = "OPENROUTER_API_KEY"
    provider_label = "OpenRouter"

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 0.95,
        site_url: str = "",
        site_name: str = "videogen",
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._site_url = site_url
        self._site_name = site_name
        super().__init__(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            api_key=api_key,
            client=client,
        )

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
        if tools:
            kwargs["tools"] = to_tools(tools)
            kwargs["tool_choice"] = "auto"
        # OpenRouter-specific routing headers (optional but recommended for analytics).
        extra_headers: dict[str, str] = {}
        if self._site_url:
            extra_headers["HTTP-Referer"] = self._site_url
        if self._site_name:
            extra_headers["X-Title"] = self._site_name
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        stream = self._client.chat.completions.create(**kwargs)
        return collect_stream(stream)

    @classmethod
    def _build_client(cls, api_key: str | None) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "the OpenRouter adapter needs the openai SDK; install it with "
                "`uv sync --extra openai` and set OPENROUTER_API_KEY"
            ) from exc
        key = api_key or os.environ.get(cls.env_var)
        if not key:
            raise RuntimeError(
                f"{cls.env_var} is not set; export it or pass api_key= explicitly"
            )
        return OpenAI(base_url=cls.base_url, api_key=key)
