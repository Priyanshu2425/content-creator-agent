"""Tree-of-Thoughts deliberation core, shared by the ToT worker variants (ADR 0011).

A generic search controller drives an ordered list of opaque *stages* (a generator + an evaluator
each) over a small tree, prunes weak branches, and returns the best leaf plus a full trace. It knows
nothing about hooks or creative direction -- the workers supply the stages, prompts, and config.
"""

from __future__ import annotations

from videogen.agent.tot.config import ToTConfig
from videogen.agent.tot.controller import (
    CallBudget,
    Scored,
    SearchResult,
    Stage,
    ThoughtState,
    ToTController,
)

__all__ = [
    "ToTConfig",
    "ToTController",
    "Stage",
    "Scored",
    "ThoughtState",
    "SearchResult",
    "CallBudget",
]
