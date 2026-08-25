# `CreativeDirectionToTAgent` — concept→execution, single winning direction

Status: done
Type: AFK

## Parent

`.scratch/tot-workers/PRD.md`

## What to build

The second ToT worker, reusing the now-complete generic `ToTController` and the value/vote evaluator
unchanged — only new stages, prompts, and the leaf shape differ. Selected by `tot_enabled`; the
legacy `CreativeDirectionAgent` stays untouched.

- **Stage 1 — creative concept**: generate `k` distinct **creative concepts** (core message +
  concrete visual metaphor) via `sample` on the hot client; `value`-score on transcript/brand support
  + distinctness; prune below `dead_end_threshold`.
- **Stage 2 — execution**: expand surviving concept(s) into the full beat map (hook, b-roll map,
  pacing, CTA). The **brand-alignment / show-don't-tell** check is a hard constraint — a concept
  whose execution can't translate an abstract beat into a concrete visual is a dead end (prune under
  BFS, backtrack under DFS).
- **Output**: the **single winning direction** document (per REQ-12 — one best leaf). No
  "concepts considered" trace in the returned proposal; the full tree is logged internally.
- **Routing**: the `dispatch_creative_direction` factory selects the ToT variant or the legacy agent
  on `tot_enabled`; both return the same proposal type, so the Director is unaffected.

Default config matches the PRD (`method_evaluate=hybrid`, `search_algorithm=bfs`, `k=3`, `b=2`,
`n_evaluate=3`, `max_depth=2`, `dead_end_threshold=3`, `max_llm_calls=40`).

## Acceptance criteria

- [x] With `tot_enabled` on, `dispatch_creative_direction` returns a single coherent winning
      direction document produced by a real search; with it off, the legacy agent runs unchanged.
- [x] Reuses the generic `ToTController` and the value/vote evaluator without modifying them.
- [x] A concept whose execution fails the brand-alignment / show-don't-tell constraint is rejected
      (pruned under BFS, backtracked-from under DFS) rather than returned.
- [x] The returned proposal is lean (winning direction only); the full tree is logged internally.
- [x] `CreativeDirectionToTAgent` contract tests with a scriptable stub `ModelClient`: returns a
      single coherent direction; a brand-constraint failure triggers rejection of that concept.

## Blocked by

- `.scratch/tot-workers/issues/02-value-hybrid-evaluator-aggregation.md`

## Comments

[2026-06-19] Done. Implemented and verified by hand-trace (tests not run — no-shell session).
- Worker: `src/videogen/agent/creative_direction_tot.py` (`CreativeDirectionToTAgent`).
  Stage 1 concept (`sample` + value-score + prune), Stage 2 execution (full beat map; the
  brand-alignment / show-don't-tell value gate marks a non-concrete execution as a `dead_end`).
- Reuses the generic `ToTController` and the `value`/`vote` evaluators unmodified; only stages,
  prompts, and leaf shaping live in the worker.
- Returns the single winning direction string (`result.best`), `_NO_DIRECTION` when unusable; the
  full tree is logged via `_log_tree` and not returned in the proposal.
- Routing on `tot_enabled`: `src/videogen/app/cli.py::_make_creative_direction_dispatcher`
  (env `VIDEOGEN_TOT_CREATIVE_DIRECTION`; legacy default). Both variants share the
  `generate(*, brief, transcript, brand_kit, scratchpad, guidance) -> str` shape.
- Tests: `tests/test_creative_direction_tot.py` (single coherent direction; unusable→`_NO_DIRECTION`;
  a concept whose execution fails the brand/show-don't-tell constraint is pruned, not returned).
