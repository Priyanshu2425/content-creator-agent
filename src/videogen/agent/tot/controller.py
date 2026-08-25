"""ToTController: the generic Tree-of-Thoughts search loop (ADR 0011, PRD §3).

The controller is deliberately blind to the domain. It drives an ordered list of opaque ``Stage``s
-- each a *generator* (produce ``k`` candidate next-thoughts from a partial state) paired with an
*evaluator* (score those candidates) -- prunes weak branches, and returns the best leaf plus the full
tree trace. Thoughts are arbitrary objects the worker defines; the controller only ever reads a
candidate's ``Scored.score`` and ``Scored.dead_end``.

Two invariants are non-negotiable (PRD §4, §9): a hard ``max_llm_calls`` budget (enforced by the
``CallBudget`` the generator/evaluator spend against) ends the search and still returns a best-so-far
leaf, and the search never descends past ``max_depth``.

Both ``search_algorithm="bfs"`` (the default) and ``"dfs"`` are implemented. BFS expands every kept
branch level-by-level and compares leaves across them; DFS dives into the best branch first and
backtracks to the next sibling only when a branch dead-ends (its best child is flagged ``dead_end``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from videogen.agent.tot.config import ToTConfig


@dataclass(frozen=True)
class ThoughtState:
    """A node in the tree: the ordered sequence of thoughts committed so far (PRD §3, the paper's
    'input + sequence of thoughts'). The root is the empty sequence."""

    thoughts: tuple[Any, ...] = ()

    @property
    def depth(self) -> int:
        return len(self.thoughts)

    def extend(self, thought: Any) -> ThoughtState:
        return ThoughtState(thoughts=(*self.thoughts, thought))

    @property
    def last(self) -> Any:
        return self.thoughts[-1] if self.thoughts else None


@dataclass(frozen=True)
class Scored:
    """An evaluated candidate thought: its aggregated ``score`` (higher is better) and whether the
    evaluator marked it a ``dead_end`` (failed a hard constraint or fell below threshold)."""

    thought: Any
    score: float
    dead_end: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class CallBudget:
    """The worker's internal model-call budget (ADR 0011: independent of the Director's budgets).

    Generator and evaluator must ``try_spend()`` before each model call and stop when it returns
    ``False``. The controller reads ``exhausted`` to end the search and return best-so-far."""

    def __init__(self, max_calls: int) -> None:
        self._max = max_calls
        self._spent = 0

    def try_spend(self, n: int = 1) -> bool:
        if self._spent + n > self._max:
            return False
        self._spent += n
        return True

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        return max(0, self._max - self._spent)

    @property
    def exhausted(self) -> bool:
        return self._spent >= self._max


# A generator: given the partial state and the shared budget, return up to k candidate thoughts.
Generator = Callable[[ThoughtState, CallBudget], list[Any]]
# An evaluator: given the partial state, its candidate thoughts, and the budget, score each.
Evaluator = Callable[[ThoughtState, list[Any], CallBudget], list[Scored]]


@dataclass(frozen=True)
class Stage:
    """One tree level: how to generate candidates and how to evaluate them.

    ``keep`` is the breadth limit applied after this stage (the paper's ``b``). ``None`` keeps every
    surviving candidate -- used for the final stage, whose leaves the worker selects from itself."""

    name: str
    generate: Generator
    evaluate: Evaluator
    keep: int | None = None


@dataclass
class TraceNode:
    """One recorded expansion, for offline debugging (PRD §3, REQ-11)."""

    stage: str
    parent_depth: int
    scored: list[Scored]
    kept: list[Scored]
    pruned_dead_ends: list[Scored]


@dataclass
class SearchResult:
    """What the controller returns: the final-depth leaves (each with its score), the single best
    leaf, the full trace, and budget accounting. The worker shapes the leaves into its proposal."""

    leaves: list[tuple[ThoughtState, Scored]]
    best: tuple[ThoughtState, Scored] | None
    trace: list[TraceNode]
    calls_spent: int
    budget_exhausted: bool


class ToTController:
    """Drives the search defined by an ordered list of stages, per the config's search algorithm."""

    def __init__(self, config: ToTConfig) -> None:
        self._config = config

    def search(self, stages: Sequence[Stage]) -> SearchResult:
        if self._config.search_algorithm == "bfs":
            return self._bfs(stages)
        if self._config.search_algorithm == "dfs":
            return self._dfs(stages)
        raise NotImplementedError(
            f"search_algorithm={self._config.search_algorithm!r} is not implemented yet"
        )

    # -- BFS -------------------------------------------------------------------------------------

    def _bfs(self, stages: Sequence[Stage]) -> SearchResult:
        budget = CallBudget(self._config.max_llm_calls)
        trace: list[TraceNode] = []
        # Frontier carries (state, the Scored that produced it). Root has no producing score.
        frontier: list[tuple[ThoughtState, Scored | None]] = [(ThoughtState(), None)]

        depth = 0
        for stage in stages:
            if depth >= self._config.max_depth or budget.exhausted:
                break
            expansions: list[tuple[ThoughtState, Scored]] = []
            for state, _ in frontier:
                if budget.exhausted:
                    break
                candidates = stage.generate(state, budget)
                if not candidates:
                    continue
                scored = stage.evaluate(state, candidates, budget)
                for sc in scored:
                    expansions.append((state.extend(sc.thought), sc))
            kept, pruned = _prune(expansions, stage.keep)
            trace.append(
                TraceNode(
                    stage=stage.name,
                    parent_depth=depth,
                    scored=[sc for _, sc in expansions],
                    kept=[sc for _, sc in kept],
                    pruned_dead_ends=pruned,
                )
            )
            if not kept:
                # Nothing survived (all empty / budget cut us off mid-stage). Stop with what we have.
                break
            frontier = [(state, sc) for state, sc in kept]
            depth += 1

        leaves = [(state, sc) for state, sc in frontier if sc is not None]
        leaves.sort(key=lambda x: x[1].score, reverse=True)
        best = leaves[0] if leaves else None
        return SearchResult(
            leaves=leaves,
            best=best,
            trace=trace,
            calls_spent=budget.spent,
            budget_exhausted=budget.exhausted,
        )

    # -- DFS -------------------------------------------------------------------------------------

    def _dfs(self, stages: Sequence[Stage]) -> SearchResult:
        """Dive into the best branch first; backtrack to the next sibling only on a dead end.

        At each node we generate + evaluate the next stage's candidates and try them best-first. A
        branch is a dead end when, at the final stage, its best child is flagged ``dead_end`` (the
        value evaluator sets this for a hard-constraint failure or a sub-threshold score) -- then we
        backtrack to the next-best unexplored sibling. The first branch that reaches the final stage
        without dead-ending wins, and its final-depth children are the leaves.

        ``max_depth`` and the ``max_llm_calls`` budget bound the search exactly as in BFS; an
        exhausted budget unwinds the recursion and we still return a best-so-far leaf (the best node
        explored at the deepest level reached)."""
        budget = CallBudget(self._config.max_llm_calls)
        trace: list[TraceNode] = []
        explored_all: list[tuple[ThoughtState, Scored]] = []  # every node created, any depth
        explored_finals: list[tuple[ThoughtState, Scored]] = []  # nodes created at the final stage
        max_depth = self._config.max_depth
        last_index = len(stages) - 1

        def is_final(stage_index: int) -> bool:
            return stage_index >= last_index or (stage_index + 1) >= max_depth

        def expand(
            state: ThoughtState, stage_index: int
        ) -> list[tuple[ThoughtState, Scored]]:
            if budget.exhausted:
                return []
            stage = stages[stage_index]
            candidates = stage.generate(state, budget)
            if not candidates:
                return []
            scored = stage.evaluate(state, candidates, budget)
            children = [(state.extend(sc.thought), sc) for sc in scored]
            children.sort(key=lambda x: x[1].score, reverse=True)
            trace.append(
                TraceNode(
                    stage=stage.name,
                    parent_depth=state.depth,
                    scored=[sc for _, sc in children],
                    kept=[children[0][1]] if children else [],
                    pruned_dead_ends=[sc for _, sc in children if sc.dead_end],
                )
            )
            explored_all.extend(children)
            return children

        def descend(
            state: ThoughtState, stage_index: int
        ) -> list[tuple[ThoughtState, Scored]] | None:
            if stage_index > last_index or state.depth >= max_depth or budget.exhausted:
                return None
            children = expand(state, stage_index)
            if not children:
                return None
            if is_final(stage_index):
                explored_finals.extend(children)
                # children are score-sorted; the best one decides if this branch is viable.
                if children[0][1].dead_end:
                    return None  # dead end -> let the caller backtrack to the next sibling
                return children
            # Intermediate stage: try viable siblings first, dead-ends only as a last resort.
            ordered = [c for c in children if not c[1].dead_end] + [
                c for c in children if c[1].dead_end
            ]
            for child_state, _sc in ordered:
                won = descend(child_state, stage_index + 1)
                if won is not None:
                    return won
            return None

        winning = descend(ThoughtState(), 0)

        if winning:
            leaves = list(winning)
        elif explored_finals:
            leaves = list(explored_finals)
        else:
            leaves = list(explored_all)
        leaves.sort(key=lambda x: x[1].score, reverse=True)
        best = leaves[0] if leaves else None
        return SearchResult(
            leaves=leaves,
            best=best,
            trace=trace,
            calls_spent=budget.spent,
            budget_exhausted=budget.exhausted,
        )


def _prune(
    expansions: list[tuple[ThoughtState, Scored]], keep: int | None
) -> tuple[list[tuple[ThoughtState, Scored]], list[Scored]]:
    """Drop dead ends, then keep the top ``keep`` by score (all of them if ``keep`` is None).

    If *every* candidate is a dead end, keep them anyway (ranked) rather than returning nothing -- a
    best-of-bad-options is more useful to the worker than an empty result."""
    alive = [e for e in expansions if not e[1].dead_end]
    pruned_dead_ends = [sc for _, sc in expansions if sc.dead_end]
    pool = alive if alive else list(expansions)
    pool.sort(key=lambda x: x[1].score, reverse=True)
    if keep is None:
        return pool, pruned_dead_ends
    return pool[:keep], pruned_dead_ends
