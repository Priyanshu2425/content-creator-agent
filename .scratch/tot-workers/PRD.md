# PRD: Tree-of-Thoughts deliberating variants for the TextHook & CreativeDirection workers

Status: ready-for-agent

> Scope note: adds **alternate ToT variants** of two existing workers (`TextHookAgent`,
> `CreativeDirectionAgent`) behind a `tot_enabled` flag. The legacy single-pass agents stay callable
> as fallback/baseline. Architecture is fixed by ADR
> [0011](../../docs/adr/0011-tot-worker-variant-deliberates-inside-the-worker.md); the Director's
> dispatch contract (ADR [0008](../../docs/adr/0008-director-dispatches-workers-in-loop.md)) is
> untouched. Glossary terms: *Worker*, *Proposal*, *Payoff frame*, *Creative concept*, *Text hook*,
> *Spoken hook*, *Creative direction*.

## Problem Statement

The Director dispatches two reasoning-heavy workers that today each commit to their **first idea** in
a single model turn. `TextHookAgent` reads the transcript, locks onto one interpretation of the
video's payoff, and generates hook candidates from that single interpretation — even though most
transcripts support several legitimate **payoff frames** (literal, emotional/identity,
contrarian), and which one it picks upstream silently caps which hooks are even possible.
`CreativeDirectionAgent` likewise produces one monolithic creative direction from one implicit
**creative concept**, with no mechanism to weigh competing concepts before committing the whole
beat map to one. Worse, where a worker does rank its own candidates, it does so *inside the same
completion that produced them* — the model rubber-stamps its own output. The result is that the two
highest-leverage creative decisions in a short (the scroll-stopping hook and the governing visual
strategy) are made by first-thought, self-graded, single-path reasoning, with no exploration of
alternatives and no way to abandon a weak interpretation.

## Solution

Give each of these two workers an alternate **Tree-of-Thoughts variant** that deliberates before it
commits: it generates several competing **frames** (payoff frames / creative concepts), scores them
with an *independent* evaluator call, prunes the weak ones, expands the survivors into finished
output (hook phrasings / a full beat map), and returns the same **proposal** shape the Director
already consumes. From the Director's point of view nothing changes — one dispatch still returns one
proposal — but the proposal is now the product of a bounded search over the decision tree rather than
a single guess.

The search controller lives **inside the worker** and self-caps its own model calls, so a dispatch
remains exactly one unit of the Director's dispatch budget no matter how much the worker deliberates.
The new variants are selected by a per-worker `tot_enabled` flag; the legacy agents remain for
fallback and A/B comparison. ToT variants run on Gemini only (they need a temperature knob the
default no-API-key client does not expose).

## User Stories

1. As the Director, I want a ToT TextHook dispatch to return the same `HookProposal` shape as the
   legacy worker, so that I place the chosen hook with `add_title` without any change to my flow.
2. As the Director, I want a ToT CreativeDirection dispatch to return one winning direction document,
   so that I read it as the "read on the room" exactly as before.
3. As the Director, I want a ToT dispatch to cost me exactly one dispatch-budget unit regardless of
   its internal deliberation, so that a deliberating worker can never starve my authoring turns.
4. As a video creator, I want the hook worker to consider multiple payoff frames before writing
   hooks, so that the final hook isn't capped by an arbitrary first interpretation of my transcript.
5. As a video creator, I want competing creative concepts weighed before one is committed, so that
   the whole video's visual strategy isn't decided by a single first guess.
6. As a video creator, I want the worker to discard a payoff frame the transcript doesn't actually
   support, so that hooks are never built on an interpretation the body can't pay off.
7. As a video creator, I want the final hook set to keep ≥3 distinct patterns, so that I never get
   five variants of the same idea even after the search narrows.
8. As a prompt engineer, I want generation and evaluation to be separate model calls, so that no
   completion grades its own output and the scores mean something.
9. As a prompt engineer, I want repeated evaluation aggregated (averaged value / majority vote), so
   that a single noisy score can't decide which frame survives.
10. As a prompt engineer, I want to choose the evaluator strategy per worker (`value`, `vote`, or
    `hybrid`), so that I can score frames in isolation but rank finished hooks comparatively.
11. As a prompt engineer, I want `hybrid` as the default evaluator, so that each gate uses the
    strategy that fits it (value at the frame gate, vote at the execution gate).
12. As a prompt engineer, I want to switch the search between `bfs` and `dfs` via a worker constant,
    so that I can trade breadth for cost without touching code.
13. As a prompt engineer, I want `bfs` as the default search, so that the worker compares hooks
    across all surviving frames rather than greedily down one.
14. As a prompt engineer, I want DFS to backtrack only when the current frame's best candidate fails
    a hard constraint or scores below a threshold, so that DFS is well-defined on a shallow tree
    instead of degenerating into greedy first-frame selection.
15. As an operator, I want a hard `max_llm_calls` cap per dispatch, so that a malformed input can
    never make a worker loop or fan out unboundedly.
16. As an operator, I want the ToT variants gated by a `tot_enabled` flag, so that I can roll them
    out per worker and instantly fall back to the legacy agent.
17. As an operator, I want ToT variants pinned to Gemini, so that the temperature-dependent sampling
    behaves predictably and never silently runs on a client that ignores temperature.
18. As a developer debugging output, I want the worker to log the full tree (frames, scores, pruned
    branches, the winning path), so that I can see *why* one frame beat another even though the
    returned proposal is lean.
19. As a developer, I want the search controller to be a single generic module shared by both
    workers, so that BFS/DFS/pruning/budget logic is written and tested once.
20. As a developer, I want each worker to supply only its own stages, prompts, and config, so that
    adding a third ToT worker later means new stages, not a new search loop.
21. As a developer, I want the legacy `TextHookAgent` and `CreativeDirectionAgent` left untouched, so
    that the baseline behavior is preserved for comparison and fallback.
22. As a developer, I want the `ModelClient` Protocol seam left unchanged, so that the ToT work
    doesn't ripple into every other client and test stub.
23. As a video creator running an ad, I want the hook worker to explore call-out and
    problem/benefit framings as competing frames, so that I get genuinely different A/B fuel.
24. As a video creator, I want a creative concept rejected when it can't translate an abstract beat
    into a concrete visual, so that "show, don't tell" is enforced rather than assumed.
25. As the Director, I want a worker that exhausts its call budget without a confident result to
    still return its best-so-far proposal (or the legacy result), so that a dispatch never returns
    nothing.

## Implementation Decisions

- **Generic shared search controller (`ToTController`).** One module owns the search loop — generate
  → evaluate → prune → expand → select — for both `bfs` and `dfs`. Interface (prose): given an
  ordered list of stages and a config, it returns the best leaf state plus a full tree trace. It
  never knows about hooks or creative concepts; stages are opaque to it. It enforces `max_depth` and
  the hard `max_llm_calls` budget, and selects the single best leaf on completion (REQ-12).
- **Stage abstraction.** A stage bundles a *generator* (produces `k` candidate thoughts from a
  partial state) and an *evaluator* (scores or ranks candidate states). Both workers are **depth-2**:
  a *frame* stage then an *execution* stage. The controller drives stages uniformly.
- **Generation = `sample`.** The generator fans out `k` independent calls on a **hot** Gemini client
  (temperature ~0.9). Candidate diversity comes from temperature, not from a propose-style single
  call. `propose` is not built.
- **Evaluation independent of generation (REQ-7).** Evaluator calls run on a separate **cold** Gemini
  client (temperature ~0.1). The worker holds two client instances; no completion evaluates its own
  output. `value` scores each candidate in isolation (averaged over `n_evaluate`); `vote` ranks all
  candidates together (majority over `n_evaluate`). `method_evaluate` ∈ {`value`, `vote`, `hybrid`},
  default `hybrid` = value at the frame gate, vote at the execution gate.
- **Search.** `search_algorithm` ∈ {`bfs`, `dfs`}, default `bfs`. BFS expands all kept frames (top
  `b`) and compares executions across them. DFS dives into the best frame first and backtracks to the
  next frame only when the current frame's best candidate fails a hard constraint *or* scores below
  `dead_end_threshold`. Under either mode the final output still satisfies the worker's contract
  (e.g. TextHook fills `n_variants` across ≥3 patterns within the winning frame(s)).
- **Controller lives inside the worker (ADR 0011 / 0008).** One dispatch → one proposal. The
  worker's internal call budget is fully independent of the Director's op and dispatch budgets; a
  dispatch costs one dispatch-budget unit irrespective of internal call count.
- **TextHook ToT decomposition.** Stage 1: generate `k` **payoff frames**, value-score on
  transcript-support + distinctness from the spoken hook, prune below threshold. Stage 2: expand
  surviving frame(s) into hook phrasings across patterns, validate against the existing hard
  constraints, vote-rank. Output: the existing `HookProposal` (ranked candidates + `recommended`).
- **CreativeDirection ToT decomposition.** Stage 1: generate `k` **creative concepts**
  (core message + concrete visual metaphor), value-score on transcript/brand support + distinctness.
  Stage 2: expand into the full beat map (hook, b-roll map, pacing, CTA); the brand-alignment /
  show-don't-tell check is a hard constraint (a DFS dead-end). Output: the **single winning
  direction** document (no "concepts considered" trace in the proposal).
- **Config object (`ToTConfig`).** Per-worker constants: `tot_enabled`, `method_generate=sample`,
  `method_evaluate=hybrid`, `search_algorithm=bfs`, `n_generate_sample (k)=3`,
  `breadth_limit (b)=2`, `n_evaluate_sample=3`, `max_depth=2`, `dead_end_threshold=3` (1–5 scale),
  `max_llm_calls=40`.
- **Routing.** The dispatcher factories select the ToT variant or the legacy agent on `tot_enabled`.
  Both return the identical proposal type, so the dispatch wiring and the Director are unaffected.
- **Gemini-only.** ToT variants construct their own Gemini clients (hot + cold). The default
  no-API-key `ClaudeCodeClient` exposes no temperature knob and cannot host a ToT worker. The
  `ModelClient` Protocol seam is unchanged.
- **Observability (REQ-11).** The worker logs the full tree (thoughts, scores, pruned branches,
  winning path) through the existing `tracing` / `log` seam, independent of the lean returned
  proposal.

## Testing Decisions

A good test here asserts **external behavior through the worker/controller contract**, never
internal call sequencing or prompt wording. The model is non-deterministic, so tests script a fake
`ModelClient` (prior art: `FixedClient` in `tests/test_text_hook.py`) — extended to a *scriptable*
stub that returns a queue of responses across the many calls a search makes, so generator and
evaluator replies can be staged deterministically.

Modules to test:

- **`ToTController`** (pure logic, stub generator/evaluator callables — no real model). Assert: BFS
  keeps top-`b` and compares across kept frames; DFS dives best-first and backtracks on a
  constraint-fail / below-threshold dead end; `max_llm_calls` is a hard stop that ends the search and
  still yields a best-so-far leaf; `max_depth` is respected; the single best leaf is selected.
- **Evaluator `value`/`vote` aggregation** (scripted-score stub client). Assert: value averages over
  `n_evaluate` and prunes below threshold; vote takes the majority pick; ties resolve deterministically.
- **`TextHookToTAgent` contract** (scriptable stub, mirrors `test_text_hook.py`). Assert: returns a
  valid `HookProposal` with `n_variants` candidates spanning ≥3 patterns and a `recommended` pick;
  degrades gracefully (legacy-style reinforce fallback) when the model output is unusable; transcript
  and brand kit reach the model.
- **`CreativeDirectionToTAgent` contract** (scriptable stub). Assert: returns a single coherent
  winning direction; a concept whose execution fails the brand-alignment / show-don't-tell constraint
  triggers a backtrack to the next concept rather than being returned.

Generator fan-out and the `tot_enabled` routing are thin glue and are exercised through the worker
contract tests rather than tested in isolation.

## Out of Scope

- `method_generate=propose` — `sample` is the only generation strategy built (Gemini temperature is
  available).
- In-prompt simulated ToT (one completion narrating the whole tree) — rejected; no evaluator
  independence, no real tree to log or budget.
- Director-as-orchestrator (the Director running the search loop; workers as per-node generators) —
  rejected; would retire ADR 0008.
- Adding `n` or `temperature` to the `ModelClient` Protocol seam.
- ToT on the default no-API-key `ClaudeCodeClient`, or any non-Gemini client.
- `search_algorithm=dfs` as the default (DFS is implemented and toggleable, but BFS is the default).
- Modifying the legacy `TextHookAgent` / `CreativeDirectionAgent`, or the other workers (`SFXAgent`,
  `BrollGeneratorAgent`, `MotionGraphicsAgent`).
- The §10 evaluation harness (baseline vs ToT quality measurement, blind human comparison). Worth
  doing before broad rollout, but not part of this build.

## Further Notes

- Cost: ≈23 model calls per BFS dispatch (value evaluation dominates: `k` frames × `n_evaluate`),
  hard-stopped at `max_llm_calls=40`. Latency benefits from parallelizing the evaluator's repeated
  calls (e.g. a thread pool over the synchronous seam), since each is an independent Gemini call.
- The `value` gate is the dominant cost term; if dispatches feel slow or expensive in practice,
  lower `n_evaluate_sample` for value before touching `k`.
- A natural follow-up is the §10 evaluation harness to quantify whether ToT beats the single-pass
  baseline by enough to justify the call multiplier, per worker.
