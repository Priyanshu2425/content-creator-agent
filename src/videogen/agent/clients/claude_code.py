"""ClaudeCodeClient: a ModelClient that authors through the Claude Code CLI (claude-agent-sdk).

Motivation: drive the authoring loop with the user's *Claude Code CLI auth* instead of an
``ANTHROPIC_API_KEY`` -- no per-token billing, no separate API rate limits (ADR 0006).

The Claude Agent SDK is an agent *harness*: it owns its own tool-use loop, executes tools
in-process, and runs async-only. That is the opposite shape of our seam, where the AuthoringLoop
owns the loop and the ModelClient only proposes one turn (ADR 0004). We reconcile the two by using
the SDK as a single-turn JSON generator: each ``next_turn`` runs a one-shot ``query`` with
``max_turns=1`` and no SDK tools, serializes the neutral history plus the tool schemas into the
prompt, and asks the model to emit exactly one tool call as JSON; we parse that back into a neutral
``AssistantTurn``. The loop, journal, gate, and op budget are unchanged.

Two consequences fall out of this shim (ADR 0006):

- vision tools (``render_still``/``scene_preview``) are hidden -- the one-shot text query has no
  image-return channel, so the agent authors from structured-text perception only (valid per ADR
  0004; the finalization gate still does real full-motion review through the video reviewer);
- there is no native tool-use recovery channel, so a hard JSON-parse failure ends the turn with an
  empty ``AssistantTurn`` (the loop then stops, as it does for any model that stops calling tools);
  a tolerant parser (fence-stripping + first-object extraction) mitigates this.

The SDK is an optional dependency, imported lazily inside the default query seam: the package and
its deterministic tests load without it. The async ``query`` is driven from the synchronous
``next_turn`` via stdlib ``asyncio``. The query seam (``query_fn``) is injectable, so the prompt
construction and reply parsing are verified end to end without the SDK or the CLI.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ToolCall,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from videogen.agent.tools import VISION_OPS

# The query seam: ``query_fn(prompt=..., system=..., model=...)`` yields provider messages. The
# default (``_sdk_query``) wraps the Claude Agent SDK; tests inject a fake.
QueryFn = Callable[..., AsyncIterator[Any]]

# The authoring loop runs many short turns, so default to Sonnet over the CLI's default (Opus): far
# cheaper across a 40-op run, and ample for emitting one validated tool call per turn. Pass
# ``model=None`` to fall back to whatever the Claude Code CLI is configured to use.
_DEFAULT_MODEL = "claude-sonnet-4-6"

_CONTRACT_PREAMBLE = (
    "You drive a video editor by emitting tool calls. You cannot run tools yourself: on each turn "
    "you propose exactly ONE tool call, the host applies it, and replies with the result and the "
    "refreshed perception. Build the composition incrementally, one validated op at a time."
)
_OUTPUT_RULES = (
    "Respond with a single JSON object and nothing else -- no prose, no markdown code fences:\n"
    '{"name": "<tool name>", "args": { ...arguments... }}\n'
    "Use exactly one tool per turn. When the composition is complete, emit "
    '{"name": "finish", "args": {}}.'
)
_NEXT_INSTRUCTION = "Now emit the next single tool call as a JSON object."


def _visible_tools(tools: Sequence[ToolSpec]) -> list[ToolSpec]:
    """Hide the vision tools: this client has no image-return channel (ADR 0006)."""
    return [t for t in tools if t.name not in VISION_OPS]


def _system_with_contract(system: str, tools: Sequence[ToolSpec]) -> str:
    """Fold the authoring system prompt, the tool catalog, and the JSON output contract together."""
    catalog = json.dumps(
        [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ],
        indent=2,
    )
    return (
        f"{system}\n\n{_CONTRACT_PREAMBLE}\n\nAvailable tools:\n{catalog}\n\n{_OUTPUT_RULES}"
    )


def _render_prompt(history: Sequence[HistoryItem]) -> str:
    """Serialize the running neutral history into a single transcript prompt.

    Each turn is one-shot, so the whole conversation is replayed every time (the loop already
    maintains it). Images are dropped with a note -- this client perceives via text only.
    """
    lines: list[str] = []
    for item in history:
        if isinstance(item, UserMessage):
            lines.append(item.text)
        elif isinstance(item, AssistantTurn):
            if item.text:
                lines.append(f"(you said: {item.text})")
            for call in item.tool_calls:
                lines.append(f"(you called {call.name} with {json.dumps(call.args)})")
        elif isinstance(item, ToolResultsMessage):
            for result in item.results:
                if result.text:
                    lines.append(f"Result: {result.text}")
                if result.images:
                    lines.append(
                        f"[{len(result.images)} image(s) omitted -- author from the text "
                        "perception above]"
                    )
    lines.append(_NEXT_INSTRUCTION)
    return "\n\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Tolerantly pull the first JSON object out of the model's text.

    Handles a bare object, a ```json fenced block, and trailing prose after the object (the first
    ``{`` is located and ``raw_decode`` stops at its matching ``}``). Returns ``None`` when no JSON
    object can be parsed -- the caller turns that into an empty turn (ADR 0006).
    """
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_turn(text: str) -> AssistantTurn:
    """Parse the model's JSON tool call into a one-call AssistantTurn (empty if unparseable)."""
    data = _extract_json(text)
    if data is None:
        return AssistantTurn()
    name = data.get("name")
    if not isinstance(name, str) or not name:
        return AssistantTurn()
    raw_args = data.get("args")
    args: dict[str, object] = raw_args if isinstance(raw_args, dict) else {}
    return AssistantTurn(tool_calls=(ToolCall(id=uuid.uuid4().hex[:8], name=name, args=args),))


async def _collect(query_fn: QueryFn, *, prompt: str, system: str, model: str | None) -> str:
    """Drain the query's assistant messages into one text blob (tool calls are disabled).

    The agent harness can exit non-zero -- e.g. ``error_max_turns`` -- *after* the model has already
    produced its answer, and the SDK surfaces that exit as a raised error. We salvage whatever
    assistant text we collected before re-raising, so a stray harness error doesn't discard a
    perfectly good tool-call JSON. A genuine setup failure (no text collected at all, e.g. the CLI
    is missing) still propagates."""
    parts: list[str] = []
    try:
        async for message in query_fn(prompt=prompt, system=system, model=model):
            for block in getattr(message, "content", None) or []:
                piece = getattr(block, "text", None)
                if isinstance(piece, str) and piece:
                    parts.append(piece)
    except Exception:
        if not parts:
            raise
    return "".join(parts)


async def _sdk_query(*, prompt: str, system: str, model: str | None) -> AsyncIterator[Any]:
    """The default query seam: a one-shot Claude Agent SDK call with tools disabled.

    Three options make the agent harness behave as a single-turn JSON generator:
    - ``tools=[]`` is the actual off-switch -- it sends ``--tools ""`` so the bundled coding agent
      starts with *no* tools (``allowed_tools`` is only a permission allowlist, it does not remove
      them). With nothing to call, the model answers in text, not a tool-use loop.
    - ``thinking`` disabled: emitting one tool-call JSON needs no reasoning, and extended thinking
      is what intermittently makes the model end a turn wanting to continue -- which trips
      ``error_max_turns``. Off, it answers directly in one turn.
    - ``max_turns`` is a small headroom rather than 1: a stray continuation can still complete
      instead of erroring, and with no tools there is nothing to run away on.

    The plain-string ``system_prompt`` replaces the default Claude Code prompt with our authoring
    contract. Authentication is the Claude Code CLI's, not an API key.
    """
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the Claude Code authoring client needs the claude-agent-sdk; install it with "
            "`uv sync --extra claude-code` and make sure the Claude Code CLI is authenticated -- "
            "it uses your CLI auth, not an API key"
        ) from exc
    options = ClaudeAgentOptions(
        system_prompt=system,
        tools=[],
        thinking={"type": "disabled"},
        max_turns=4,
        model=model,
    )
    async for message in query(prompt=prompt, options=options):
        yield message


class ClaudeCodeClient:
    """A ModelClient that drives the authoring loop through the Claude Code CLI (no API key)."""

    consumes_images = False  # one-shot text query drops images, so it authors blind (ADR 0007)

    def __init__(
        self,
        *,
        model: str | None = _DEFAULT_MODEL,
        query_fn: QueryFn | None = None,
    ) -> None:
        self._model = model
        self._query_fn: QueryFn = query_fn if query_fn is not None else _sdk_query

    def next_turn(
        self,
        *,
        system: str,
        history: Sequence[HistoryItem],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        visible = _visible_tools(tools)
        full_system = _system_with_contract(system, visible)
        prompt = _render_prompt(history)
        text = asyncio.run(
            _collect(self._query_fn, prompt=prompt, system=full_system, model=self._model)
        )
        return _parse_turn(text)
