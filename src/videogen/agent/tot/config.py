"""ToTConfig: the per-worker tuning constants for a Tree-of-Thoughts worker (ADR 0011, PRD §4).

These are the knobs the reference paper exposes (arXiv:2305.10601), named to match: ``k`` candidates
per node, ``b`` states kept after pruning, repeated evaluation, the generate/evaluate/search
strategies, and the hard call budget. Defaults are the agreed operating point; a worker may override
any of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MethodGenerate = Literal["sample"]
MethodEvaluate = Literal["value", "vote", "hybrid"]
SearchAlgorithm = Literal["bfs", "dfs"]


@dataclass(frozen=True)
class ToTConfig:
    """Tuning constants for one ToT worker. See PRD §4."""

    tot_enabled: bool = True
    method_generate: MethodGenerate = "sample"
    method_evaluate: MethodEvaluate = "hybrid"
    search_algorithm: SearchAlgorithm = "bfs"

    n_generate_sample: int = 3  # k -- candidate thoughts generated per node
    breadth_limit: int = 2  # b -- states kept after pruning at each BFS level
    n_evaluate_sample: int = 3  # repeated evaluations, aggregated before pruning
    max_depth: int = 2  # number of thought stages (frame -> execution)
    dead_end_threshold: float = 3.0  # on the 1-5 value scale; below this a branch is a dead end
    max_llm_calls: int = 40  # hard per-dispatch budget (runaway stop)

    # Temperatures for the two client instances the worker holds.
    hot_temperature: float = 0.9  # generator -- diverse i.i.d. samples
    cold_temperature: float = 0.1  # evaluator -- stable scoring
