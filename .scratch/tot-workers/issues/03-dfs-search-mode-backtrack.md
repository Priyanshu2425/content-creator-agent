# Add `dfs` search mode + backtrack semantics

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/tot-workers/PRD.md`

## What to build

Extend the generic `ToTController` with a depth-first search mode alongside the existing BFS, exposed
through the `search_algorithm` toggle (`bfs` | `dfs`) on `ToTConfig`. BFS stays the default.

DFS dives into the **best-scoring frame first**, expands it to completion, and **backtracks to the
next unexplored frame only when the current frame's best candidate fails a hard constraint OR scores
below `dead_end_threshold`** — so DFS is well-defined on the shallow depth-2 tree instead of
degenerating into greedy first-frame selection. Under DFS the worker's output contract still holds
(e.g. TextHook fills `n_variants` across ≥3 patterns within the winning frame).

The lookahead/progress limit collapses into the dead-end trigger at depth 2. The `max_llm_calls`
hard stop applies to DFS exactly as to BFS.

## Acceptance criteria

- [ ] `search_algorithm` toggles between `bfs` and `dfs`; both are reachable and correct; default is
      `bfs`.
- [ ] DFS dives into the best frame first and only backtracks on a hard-constraint failure or a
      below-`dead_end_threshold` score.
- [ ] DFS that exhausts all frames without clearing the bar still returns a best-so-far leaf.
- [ ] DFS output satisfies the same worker contract as BFS (`n_variants`, ≥3 patterns).
- [ ] `max_llm_calls` hard stop holds under DFS.
- [ ] `ToTController` tests with a stub generator/evaluator: DFS dives best-first; backtracks on a
      scripted dead-end; does not backtrack when the first frame clears the bar; budget hard stop.

## Blocked by

- `.scratch/tot-workers/issues/02-value-hybrid-evaluator-aggregation.md`
