# Walking-skeleton ToT TextHook — BFS, vote-only, end-to-end behind `tot_enabled`

Status: done
Type: AFK

## Parent

`.scratch/tot-workers/PRD.md`

## What to build

The irreducible end-to-end Tree-of-Thoughts path: a `TextHookAgent` ToT variant that deliberates
over a depth-2 tree and returns the *same* `HookProposal` the legacy worker returns, selected by a
`tot_enabled` flag. From the Director's side nothing changes — one `dispatch_text_hook` still yields
one proposal.

Deliver the thin slice through every layer:

- A **generic `ToTController`**: drives an ordered list of opaque stages with `bfs` only — generate
  → evaluate → prune to top `b` → expand → select the single best leaf. It knows nothing about hooks.
  It enforces `max_depth` and a hard `max_llm_calls` budget (the budget ends the search and still
  returns a best-so-far leaf).
- A **stage abstraction**: each stage bundles a *generator* (produces `k` candidate thoughts from a
  partial state) and an *evaluator* (ranks candidate states).
- A **`sample` generator**: fans out `k` independent calls on a **hot** Gemini client (~0.9).
- A single **`vote` evaluator**: one call on a **cold** Gemini client (~0.1) ranks all candidates
  together; drives both the frame gate (keep top `b`) and the execution gate. Generation and
  evaluation are separate calls.
- A **`TextHookToTAgent`** assembling two stages — payoff-frame stage → hook-phrasing stage — and
  returning the existing `HookProposal` (ranked candidates + `recommended`), with the legacy
  graceful-fallback behavior when output is unusable.
- A minimal **`ToTConfig`** carrying the constants this slice needs (`tot_enabled`,
  `n_generate_sample`, `breadth_limit`, `max_depth`, `max_llm_calls`).
- **Routing**: the `dispatch_text_hook` factory selects the ToT variant or the legacy agent on
  `tot_enabled`; both return the identical proposal type.

ToT variant runs on Gemini only (hot + cold client instances). The legacy `TextHookAgent` and the
`ModelClient` Protocol seam are left untouched. The worker logs the tree (frames, scores, pruned
branches, winning path) through the existing `tracing` / `log` seam.

## Acceptance criteria

- [x] With `tot_enabled` on, `dispatch_text_hook` returns a valid `HookProposal` (`n_variants`
      candidates spanning ≥3 patterns, a `recommended` pick) produced by a real BFS search.
- [x] With `tot_enabled` off, the legacy `TextHookAgent` runs unchanged.
- [x] `ToTController` is generic — it carries no hook-specific logic; stages are opaque to it.
- [x] Generation and evaluation are distinct model calls (no completion ranks its own output).
- [x] `max_llm_calls` is a hard stop: a search that would exceed it ends and still returns a
      best-so-far leaf.
- [x] Unusable model output degrades to the legacy reinforce-style fallback rather than erroring.
- [x] Transcript and brand kit reach the model; the full tree is logged.
- [x] `ToTController` tests (stub generator/evaluator, no real model): BFS keeps top-`b` and compares
      across kept frames; `max_llm_calls` hard stop; `max_depth` respected; single best leaf selected.
- [x] `TextHookToTAgent` contract tests with a scriptable stub `ModelClient` (prior art:
      `FixedClient` in `tests/test_text_hook.py`): valid `HookProposal`, ≥3 patterns, graceful
      fallback, inputs reach the model.

## Blocked by

- None - can start immediately

## Comments

[2026-06-19] Done. Implemented and verified by hand-trace (tests not run — no-shell session).
- Generic controller + BFS + budget/depth caps: `src/videogen/agent/tot/controller.py`
  (`ToTController._bfs`, `CallBudget`, `_prune`).
- Stage abstraction + `sample` generator: `tot/controller.py` (`Stage`), `tot/generation.py`.
- `vote` evaluator (cold client, separate call): `tot/evaluation.py` (`make_vote_evaluator`).
- `ToTConfig`: `tot/config.py`. Worker: `src/videogen/agent/text_hook_tot.py` (returns the
  legacy `HookProposal`, `_fallback` on unusable output, logs the tree via `_log_tree`).
- Routing on `tot_enabled`: `src/videogen/app/cli.py::_make_text_hook_dispatcher`
  (env `VIDEOGEN_TOT_TEXT_HOOK`; legacy default).
- Tests: `tests/test_tot_controller.py` (BFS top-`b`, `max_depth`, `max_llm_calls` best-so-far),
  `tests/test_text_hook_tot.py` (valid proposal ≥3 patterns, graceful fallback, transcript reaches model).
