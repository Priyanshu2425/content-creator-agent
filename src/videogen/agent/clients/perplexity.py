"""PerplexityModelClient: ModelClient over Perplexity's OpenAI-compatible API.

A thin subclass of OpenAICompatModelClient: only the Perplexity base URL, the PERPLEXITY_API_KEY
env var, and a default ``sonar`` model differ; all wire translation lives in the shared base.

Note: Perplexity's sonar models are search-augmented and their tool/function-calling support is
narrower than a general agentic model's. This is wired the same way as the other adapters so it can
be swapped in, but the authoring loop's heavy tool use may behave differently here.
"""

from __future__ import annotations

from typing import Any

from videogen.agent.clients._openai_compat import OpenAICompatModelClient

_DEFAULT_MODEL = "sonar-pro"


class PerplexityModelClient(OpenAICompatModelClient):
    """A ``ModelClient`` that drives the authoring loop via Perplexity's OpenAI-compatible API."""

    base_url = "https://api.perplexity.ai"
    env_var = "PERPLEXITY_API_KEY"
    provider_label = "Perplexity"

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 0.95,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            api_key=api_key,
            client=client,
        )
