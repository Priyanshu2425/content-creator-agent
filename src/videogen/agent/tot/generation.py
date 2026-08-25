"""Sample generation for ToT stages (PRD §3, REQ-3).

``method_generate="sample"``: call the generation prompt ``k`` times i.i.d. on the *hot* client and
treat each completion as one candidate thought. Diversity comes from the hot client's temperature
(ADR 0011 -- ToT workers are Gemini-only precisely so this knob exists). Every call is gated by the
shared ``CallBudget`` so generation can never exceed the worker's hard call cap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from videogen.agent.model import ModelClient, UserMessage
from videogen.agent.tot.controller import CallBudget, Generator, ThoughtState


def make_sample_generator(
    *,
    client: ModelClient,
    system: str,
    build_payload: Callable[[ThoughtState], str],
    parse: Callable[[str, ThoughtState], Any | None],
    k: int,
) -> Generator:
    """Build a generator that draws ``k`` i.i.d. candidate thoughts from ``client``.

    ``build_payload`` renders the user message for a partial state; ``parse`` turns one completion
    into a thought (or ``None`` to discard an unusable reply)."""

    def generate(state: ThoughtState, budget: CallBudget) -> list[Any]:
        out: list[Any] = []
        for _ in range(k):
            if not budget.try_spend(1):
                break
            payload = build_payload(state)
            turn = client.next_turn(
                system=system, history=[UserMessage(payload)], tools=[]
            )
            thought = parse(turn.text or "", state)
            if thought is not None:
                out.append(thought)
        return out

    return generate
