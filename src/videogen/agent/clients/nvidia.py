"""NvidiaModelClient: ModelClient over NVIDIA's OpenAI-compatible inference API (NIM).

A thin subclass of OpenAICompatModelClient: it only adds the NVIDIA base URL, the NVIDIA_API_KEY
env var, and the ``chat_template_kwargs.thinking`` switch some NIM-hosted models honour. All wire
translation lives in the shared base.
"""

from __future__ import annotations

from typing import Any

from videogen.agent.clients._openai_compat import OpenAICompatModelClient

_DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro"


class NvidiaModelClient(OpenAICompatModelClient):
    """A ``ModelClient`` that drives the authoring loop via NVIDIA's OpenAI-compatible API."""

    base_url = "https://integrate.api.nvidia.com/v1"
    env_var = "NVIDIA_API_KEY"
    provider_label = "NVIDIA"

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 0.95,
        thinking: bool = False,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            extra_body={"chat_template_kwargs": {"thinking": thinking}},
            api_key=api_key,
            client=client,
        )
