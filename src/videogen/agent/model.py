"""Provider-agnostic model seam for the authoring loop (Phase 8, ADR 0004).

The loop talks to a ``ModelClient`` -- never an SDK directly -- so the model is swappable: a stub in
tests, a real Anthropic (or other provider) adapter later, with no change to the loop. The
message and tool types here are deliberately neutral; an adapter is the only place that translates
them to and from a provider's wire shapes (Anthropic ``tool_use``/``tool_result`` blocks, etc.).

The conversation is a list of neutral ``HistoryItem``s the loop maintains and replays each turn:
a ``UserMessage`` (the brief + structured perception), an ``AssistantTurn`` (the model's narration
plus the tool calls it wants run), and a ``ToolResultsMessage`` (our replies -- perception text or
vision images). ``ModelClient.next_turn`` consumes the running history and returns the next turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model: its name, a description, and a JSON-Schema input shape."""

    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True)
class ToolCall:
    """The model's request to invoke one tool, with a correlation ``id`` and decoded ``args``."""

    id: str
    name: str
    args: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Our reply to one ``ToolCall``: perception ``text``, or vision ``images`` (PNG bytes)."""

    call_id: str
    text: str | None = None
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class UserMessage:
    """A plain user-role message -- the opening brief plus the initial structured perception."""

    text: str


@dataclass(frozen=True)
class AssistantTurn:
    """One model response: optional narration plus the tool calls it wants the loop to run."""

    tool_calls: tuple[ToolCall, ...] = ()
    text: str | None = None


@dataclass(frozen=True)
class ToolResultsMessage:
    """The loop's reply for a turn: one ``ToolResult`` per call the assistant made."""

    results: tuple[ToolResult, ...]


HistoryItem = UserMessage | AssistantTurn | ToolResultsMessage


class ModelClient(Protocol):
    """The swappable model. Given the system prompt, the running history, and the available tools,
    return the next assistant turn. Implementations: a scripted stub (tests) or a real provider
    adapter (deferred) -- the loop never depends on which."""

    def next_turn(
        self,
        *,
        system: str,
        history: Sequence[HistoryItem],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn: ...
