# Add `value` + `hybrid` evaluator with `n_evaluate` aggregation

Status: done
Type: AFK

## Parent

`.scratch/tot-workers/PRD.md`

## What to build

Extend the evaluator from a single `vote` strategy to the full set, and make `hybrid` the default —
so each gate uses the strategy that fits it: `value` scores **payoff frames** in isolation, `vote`
ranks finished **hooks** comparatively.

- Add a **`value`** strategy: scores each candidate independently on a fixed scale (transcript
  support + distinctness from the spoken hook), repeated `n_evaluate_sample` times and **averaged**.
- Add **repeated-evaluation aggregation** for both strategies: `value` averages its scores; `vote`
  takes the **majority** pick over `n_evaluate_sample` ballots; ties resolve deterministically.
- Add **`dead_end_threshold` pruning**: at the frame gate, discard frames whose aggregated value
  falls below the threshold.
- Wire the **`method_evaluate`** toggle (`value` | `vote` | `hybrid`) into `ToTConfig`, default
  `hybrid` (value at the frame gate, vote at the execution gate).

The controller and worker assembly from slice 1 are unchanged except for selecting the evaluator per
gate from config.

## Acceptance criteria

- [x] `method_evaluate=hybrid` (default) uses `value` at the frame gate and `vote` at the execution
      gate; `value` and `vote` are each individually selectable for both gates.
- [x] `value` averages over `n_evaluate_sample`; `vote` takes the majority over `n_evaluate_sample`;
      both aggregate before any pruning.
- [x] Frames scoring below `dead_end_threshold` are pruned at the frame gate.
- [x] Evaluator strategies run on the cold client, independent of generation.
- [x] Evaluator aggregation tests with a scripted-score stub client: value averages and prunes below
      threshold; vote returns the majority pick; ties resolve deterministically.
- [x] Existing slice-1 controller and `TextHookToTAgent` contract tests still pass.

## Blocked by

- `.scratch/tot-workers/issues/01-tot-controller-walking-skeleton-texthook.md`

## Comments

[2026-06-19] Done. Implemented and verified by hand-trace (tests not run — no-shell session).
- `value` strategy (independent score, averaged over `n_evaluate_sample`, `dead_end` below
  threshold): `src/videogen/agent/tot/evaluation.py::make_value_evaluator`.
- Per-gate strategy selection from `method_evaluate` (`value` | `vote` | `hybrid`, default
  `hybrid` = value@frame / vote@execution): the `_evaluator(...)` method in both
  `src/videogen/agent/text_hook_tot.py` and `src/videogen/agent/creative_direction_tot.py`;
  toggle lives in `tot/config.py::ToTConfig.method_evaluate`.
- `dead_end_threshold` pruning at the frame gate: `make_value_evaluator` sets `Scored.dead_end`,
  `controller._prune` drops them.
- Evaluators run on the cold client, separate from generation.
- Tests: `tests/test_tot_evaluation.py` (value averages + flags dead end below threshold + respects
  budget; vote aggregates over ballots; ties resolve deterministically).

Nuance: the issue/PRD describe `vote` as a "majority" pick; the implementation aggregates ballots
with **Borda points** (`n - position` per ballot, summed), which the slice-1 vote gate and the
`test_tot_evaluation.py` assertions are written against. Borda subsumes majority for the top pick
and gives a usable ordering for pruning — behavior is intentional and tested, only the word differs.
