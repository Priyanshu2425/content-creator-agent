"""The chain pipeline: a fixed-order alternative to the Director loop (ADR 0013).

Where the director-loop pipeline (ADR 0008) has the Director *pull* workers on demand, the chain
runs them in a fixed order and a terminal **Composer** emits the Composition directly. The two
pipelines coexist, share the same workers, and are selected per run from the CLI. This package holds
the chain-only pieces: the ``ChainConfig`` knobs, the deterministic ``prep`` step, the pure
``role_check`` predicate, the ``Composer``, and the ``ChainStrategy`` that sequences them.
"""

from __future__ import annotations

from videogen.agent.chain.composer import Composer, ComposerError
from videogen.agent.chain.config import ChainConfig
from videogen.agent.chain.prep import ResolvedBeat, prep
from videogen.agent.chain.role_check import RoleViolation, wrong_role_backfill_violations
from videogen.agent.chain.strategy import (
    AuthoringStrategy,
    ChainStageError,
    ChainStrategy,
    DirectorLoopStrategy,
)

__all__ = [
    "ChainConfig",
    "ResolvedBeat",
    "prep",
    "RoleViolation",
    "wrong_role_backfill_violations",
    "Composer",
    "ComposerError",
    "AuthoringStrategy",
    "ChainStrategy",
    "DirectorLoopStrategy",
    "ChainStageError",
]
