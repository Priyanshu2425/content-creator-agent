"""ToTController (ADR 0011): the generic BFS search loop.

The controller is domain-blind, so these tests drive it with plain stub generator/evaluator
callables -- no model at all -- and assert the search behaviour: it keeps the top ``b`` per level and
compares leaves across the kept branches, it respects ``max_depth``, and ``max_llm_calls`` is a hard
stop that still returns a best-so-far leaf.
"""

from __future__ import annotations

from videogen.agent.tot.config import ToTConfig
from videogen.agent.tot.controller import CallBudget, Scored, Stage, ThoughtState, ToTController


def _gen_map(mapping):
    """Generator stub: returns the candidate list registered for the parent's last thought, spending
    one budget unit per candidate (so budget tests can bite on generation)."""

    def generate(state: ThoughtState, budget: CallBudget):
        out = []
        for v in mapping.get(state.last, []):
            if not budget.try_spend(1):
                break
            out.append(v)
        return out

    return generate


def _eval_scores(scores, dead_ends=()):
    """Evaluator stub: scores each candidate from a fixed table; spends no budget."""

    def evaluate(state: ThoughtState, candidates: list, budget: CallBudget):
        return [
            Scored(thought=c, score=float(scores.get(c, 0.0)), dead_end=c in dead_ends)
            for c in candidates
        ]

    return evaluate


def test_bfs_keeps_top_b_and_compares_leaves_across_kept_branches() -> None:
    cfg = ToTConfig(search_algorithm="bfs", max_depth=2, breadth_limit=2, max_llm_calls=100)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b", "c"]}),
        evaluate=_eval_scores({"a": 3, "b": 2, "c": 1}),
        keep=2,
    )
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1", "a2"], "b": ["b1"], "c": ["c1"]}),
        evaluate=_eval_scores({"a1": 5, "a2": 1, "b1": 4, "c1": 9}),
        keep=None,
    )

    result = ToTController(cfg).search([frame, phrasing])

    leaf_thoughts = {sc.thought for _, sc in result.leaves}
    # 'c' was pruned at the frame gate (only top-2 a,b kept), so its high-scoring child c1 is never
    # reached -- proving pruning happened and leaves come only from kept branches.
    assert leaf_thoughts == {"a1", "a2", "b1"}
    assert "c1" not in leaf_thoughts
    # Best leaf is the highest-scoring reachable one (a1=5), not the unreachable c1=9.
    assert result.best is not None
    assert result.best[1].thought == "a1"


def test_max_depth_stops_the_search_early() -> None:
    cfg = ToTConfig(search_algorithm="bfs", max_depth=1, breadth_limit=5, max_llm_calls=100)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b"]}),
        evaluate=_eval_scores({"a": 2, "b": 1}),
        keep=5,
    )
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1"], "b": ["b1"]}),
        evaluate=_eval_scores({"a1": 1, "b1": 1}),
        keep=None,
    )

    result = ToTController(cfg).search([frame, phrasing])

    # Only the frame stage ran; leaves are depth-1 states.
    assert len(result.trace) == 1
    assert all(state.depth == 1 for state, _ in result.leaves)


def test_max_llm_calls_is_a_hard_stop_with_best_so_far() -> None:
    cfg = ToTConfig(search_algorithm="bfs", max_depth=2, breadth_limit=5, max_llm_calls=2)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b", "c"]}),  # wants 3 calls, budget allows 2
        evaluate=_eval_scores({"a": 3, "b": 2, "c": 1}),
        keep=5,
    )
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1"], "b": ["b1"]}),
        evaluate=_eval_scores({"a1": 9, "b1": 9}),
        keep=None,
    )

    result = ToTController(cfg).search([frame, phrasing])

    assert result.budget_exhausted is True
    assert result.calls_spent == 2
    # Search couldn't reach the phrasing stage, but still returns a best-so-far (depth-1) leaf.
    assert result.best is not None
    assert result.best[1].thought == "a"


def test_dfs_dives_into_the_best_frame_first_without_exploring_siblings() -> None:
    cfg = ToTConfig(search_algorithm="dfs", max_depth=2, max_llm_calls=100)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b", "c"]}),
        evaluate=_eval_scores({"a": 3, "b": 2, "c": 1}),
    )
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1", "a2"], "b": ["b1"], "c": ["c1"]}),
        evaluate=_eval_scores({"a1": 5, "a2": 1, "b1": 4, "c1": 9}),
    )

    result = ToTController(cfg).search([frame, phrasing])

    leaf_thoughts = {sc.thought for _, sc in result.leaves}
    # Dives into the best frame 'a', its best child is fine, so it wins immediately -- siblings b/c
    # are never expanded (no b1/c1).
    assert leaf_thoughts == {"a1", "a2"}
    assert result.best is not None
    assert result.best[1].thought == "a1"


def test_dfs_does_not_backtrack_when_best_child_clears_the_bar() -> None:
    cfg = ToTConfig(search_algorithm="dfs", max_depth=2, max_llm_calls=100)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b"]}),
        evaluate=_eval_scores({"a": 3, "b": 2}),
    )
    # 'a' is explored first; its best child a1 is NOT a dead end, so b is never touched.
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1"], "b": ["b1"]}),
        evaluate=_eval_scores({"a1": 5, "b1": 9}),
    )

    result = ToTController(cfg).search([frame, phrasing])

    leaf_thoughts = {sc.thought for _, sc in result.leaves}
    assert leaf_thoughts == {"a1"}
    assert "b1" not in leaf_thoughts
    assert result.best[1].thought == "a1"


def test_dfs_backtracks_to_next_frame_when_best_child_is_a_dead_end() -> None:
    cfg = ToTConfig(search_algorithm="dfs", max_depth=2, max_llm_calls=100)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b"]}),
        evaluate=_eval_scores({"a": 3, "b": 2}),  # 'a' is the higher-scored frame, tried first
    )
    # 'a's only child a1 is a dead end -> backtrack to 'b', whose child b1 is viable.
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1"], "b": ["b1"]}),
        evaluate=_eval_scores({"a1": 8, "b1": 4}, dead_ends=("a1",)),
    )

    result = ToTController(cfg).search([frame, phrasing])

    assert result.best is not None
    # Backtracked past the higher-scored frame 'a' (dead end) to land on b1.
    assert result.best[1].thought == "b1"
    assert {sc.thought for _, sc in result.leaves} == {"b1"}


def test_dfs_max_llm_calls_hard_stop_returns_best_so_far() -> None:
    cfg = ToTConfig(search_algorithm="dfs", max_depth=2, max_llm_calls=2)
    frame = Stage(
        name="frame",
        generate=_gen_map({None: ["a", "b", "c"]}),  # wants 3 calls, budget allows 2
        evaluate=_eval_scores({"a": 3, "b": 2, "c": 1}),
    )
    phrasing = Stage(
        name="phrasing",
        generate=_gen_map({"a": ["a1"], "b": ["b1"]}),
        evaluate=_eval_scores({"a1": 9, "b1": 9}),
    )

    result = ToTController(cfg).search([frame, phrasing])

    assert result.budget_exhausted is True
    assert result.calls_spent == 2
    # Never reached the phrasing stage; still returns a best-so-far depth-1 leaf (the best frame 'a').
    assert result.best is not None
    assert result.best[1].thought == "a"


def test_call_budget_try_spend_enforces_the_cap() -> None:
    budget = CallBudget(2)
    assert budget.try_spend() is True
    assert budget.try_spend() is True
    assert budget.try_spend() is False
    assert budget.exhausted is True
    assert budget.spent == 2
