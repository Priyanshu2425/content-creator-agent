"""Swappable authoring ``ModelClient`` adapters (one per provider).

Each class here implements the provider-agnostic ``ModelClient`` seam (``agent.model``) so any of
them can be wired into the authoring pipeline interchangeably; ``cli.build_default_pipeline`` picks
one. Add a new provider by dropping a module in this package and exporting its client below — an
OpenAI-compatible provider is a few lines on ``OpenAICompatModelClient``.

Imports are lazy (via ``__getattr__``) so importing this package does not pull in any optional
provider SDK; the SDK loads only when a concrete client is actually constructed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from videogen.agent.clients.anthropic import AnthropicModelClient
    from videogen.agent.clients.claude_code import ClaudeCodeClient
    from videogen.agent.clients.gemini import GeminiModelClient
    from videogen.agent.clients.nvidia import NvidiaModelClient
    from videogen.agent.clients.openrouter import OpenRouterModelClient
    from videogen.agent.clients.perplexity import PerplexityModelClient

__all__ = [
    "AnthropicModelClient",
    "ClaudeCodeClient",
    "GeminiModelClient",
    "NvidiaModelClient",
    "OpenRouterModelClient",
    "PerplexityModelClient",
]

_MODULES = {
    "AnthropicModelClient": "anthropic",
    "ClaudeCodeClient": "claude_code",
    "GeminiModelClient": "gemini",
    "NvidiaModelClient": "nvidia",
    "OpenRouterModelClient": "openrouter",
    "PerplexityModelClient": "perplexity",
}


def __getattr__(name: str) -> Any:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
