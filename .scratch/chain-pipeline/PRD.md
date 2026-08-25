# PRD: Chain pipeline — a fixed-order alternative to the Director loop

Status: ready-for-agent

> Scope note: introduces the **chain pipeline** as a second, coexisting pipeline alongside the
> director-loop pipeline — see `docs/adr/0013-chain-pipeline-fixed-order-alternative-to-director-loop.md`.
> Glossary terms used here (Pipeline, Director-loop pipeline, Chain pipeline, Pipeline strategy,
> Composer, Prep step, Worker, Proposal, BeatPlan/Beat, Brand kit) are defined in `CONTEXT.md`.
> Depends on ADRs 0008 (Director dispatches workers), 0009 (SFXAgent authority), 0011 (ToT worker
> variants), 0012 (BeatPlan binds direction to placement). Supersedes none of them.

## Problem Statement

We have a deliberate, adaptive **Director-loop pipeline** (ADR 0008): the Director *pulls* workers on
demand, decides which specialist to dispatch and when, and turns each accepted **proposal** into
validated Builder ops one per turn. ADR 0012 then made placement deterministic inside that loop (a
typed **BeatPlan** plus `execute(beat_plan, assets) -> ops`), and ADR 0011 added deliberating ToT
worker variants.

Those additions raise a question we cannot currently answer: now that workers emit a typed plan and
typed beat-keyed assets, is the Director's *adaptive dispatch* still earning its cost — or would a
**fixed worker order** plus a single integrator agent produce an equal-or-better video, more simply
and more testably? We can't answer it by rewriting the Director: that destroys the loop's machinery
and makes the comparison impossible. There is no way today to run the alternative topology against the
loop with the workers held constant.

## Solution

A second, **coexisting** pipeline — the **chain pipeline** — selected per run from the CLI
(`make --pipeline {director-loop, chain}`, default `director-loop`). It shares the front half
(ingest → transcribe → ideal-cuts) and the *same worker code*, and forks only on how authoring
happens. After the front half it runs **creative direction → { broll, motion-graphics, text hook }**
(the three in parallel) → a deterministic **prep** step → a terminal **Composer** agent → **SFX** →
render. The pipeline decides dispatch, not a model; there is no adaptive Director.

The **Composer** is a single no-tools Opus 4.8 Claude Code SDK call that emits a **Composition
directly** from a deterministically prepared bundle. It does LLM-decided placement — knowingly opting
out of ADR 0012's deterministic `execute()` *for this pipeline only* — but every part that has a
ground-truth answer is done deterministically *before* it: beat→asset matching and word-index→seconds
resolution happen in the prep step, and a wrong-role back-fill check guards the output. The Composer
decides only judgment (region, layout, treatment, gap-fill).

The result is a clean experiment grid: **director-loop vs chain** (topology) × **ToT on/off** (worker
depth), with the workers as the controlled variable, so a quality difference is attributable to the
topology rather than to two different worker implementations.

## User Stories

1. As a creator, I want to choose which pipeline produces my video, so that I can compare the
   adaptive Director against the fixed chain on my own footage.
2. As a creator, I want `--pipeline director-loop` (the default) to behave exactly as it does today,
   so that adopting the chain never changes my existing runs.
3. As a creator, I want `--pipeline chain` to produce a finished mp4 from the same inputs, so that the
   two pipelines are drop-in comparable.
4. As an evaluator, I want both pipelines to call the *same* workers, so that any quality difference
   reflects the topology, not a forked broll/creative-direction implementation.
5. As an evaluator, I want a single `--tot` flag I can apply to either pipeline, so that I can isolate
   the contribution of ToT deliberation independently of the topology.
6. As an evaluator, I want `--tot` to error clearly when Gemini is not wired, so that I never get a
   silent single-pass fallback masquerading as a ToT run.
7. As a developer, I want the chain to run creative direction first, then broll, motion-graphics, and
   text hook in parallel, so that wall-clock is the slowest worker, not their sum.
8. As a developer, I want text hook to consume the creative concept (not generated assets), so that it
   parallelizes with the asset generators and stays coherent with the BeatPlan's frame.
9. As a developer, I want motion-graphics to run *before* the Composer alongside broll, so that its
   beat-keyed assets are visible to the agent that places them.
10. As a developer, I want a deterministic prep step that zips each beat to its asset by `beat_id`, so
    that the Composer never re-discovers which asset serves which beat.
11. As a developer, I want a missing asset to surface as an explicit `None` pair from prep, so that a
    failed generation is visible rather than silently absent.
12. As a developer, I want the prep step to resolve each beat's word-index `transcript_span` to
    concrete `[start_s, end_s]`, so that the Composer never does timestamp arithmetic.
13. As a developer, I want the Composer to receive time-anchored `(Beat, Asset|None)` pairs, so that
    its only job is judgment: region, layout, treatment, gap-fill.
14. As a developer, I want the Composer to emit a Composition directly (no Builder ops, no kernel
    ops), so that ADR 0008's "Director is the only kernel-op author" stays literally true.
15. As a developer, I want the Composer's output validated by the IR validator with a bounded
    re-prompt on failure, so that a malformed Composition is corrected rather than shipped or crashed.
16. As a creator, I want the Composer to *never* place an asset on a beat whose role differs from the
    asset's source-beat role, so that the ADR 0012 wrong-role back-fill bug cannot recur.
17. As a developer, I want the wrong-role rule asserted on the emitted Composition and re-prompted on
    violation, so that the guarantee is enforced, not merely requested in the prompt.
18. As a developer, I want the chain to coordinate stages with typed objects only (no prose
    scratchpad), so that the ADR 0012 prose re-interpretation drift channel stays closed.
19. As a developer, I want SFX reused unchanged as a fixed post-Composer stage that layers sound onto
    the Composition, so that the Composer owns structure and SFX owns sound.
20. As a developer, I want the SFX stage to no-op cleanly when there is nothing to score, so that a
    fixed stage costs nothing on videos that need no sound.
21. As a creator, I want a creative-direction failure to fail the run with a named stage error, so
    that I know the BeatPlan (which everything depends on) could not be produced.
22. As a creator, I want a broll or motion-graphics failure to degrade rather than fail, so that a
    partial asset set still yields a video.
23. As a creator, I want an all-`None` asset bundle to still produce a host-only talking-head cut, so
    that I get a plain video rather than a hard failure (consistent with talking-head-first, ADR 0005).
24. As a creator, I want a text-hook failure to degrade to no opening overlay, so that a missing hook
    is a lesser video, not a broken one.
25. As a creator, I want a Composer failure (after bounded re-prompt) to fail the run with a named
    stage error, so that I'm told the artifact itself could not be authored.
26. As a creator, I want an SFX failure to degrade to a silent-SFX video, so that sound problems never
    block rendering.
27. As a developer, I want BeatPlan forced on in the chain, so that beat-keyed placement (the chain's
    contract) is never silently absent.
28. As a developer, I want `tot_enabled` to remain per-worker config even though the CLI exposes one
    flag, so that I can later isolate one worker's ToT contribution without new CLI surface.
29. As a developer, I want the worker callable seam (`(inputs) -> proposal`) to be the shared
    interface, so that the loop's dispatch-tool becomes a thin adapter over the same code.
30. As a developer, I want the prep step and the role-check predicate to be pure and unit-testable in
    isolation, so that the determinism guarantees have fast, fixture-backed tests.
31. As a developer, I want the strategy seam to sit after ideal-cuts, so that the shared front half is
    written once and each strategy owns its back half fully.

## Implementation Decisions

**Topology (ADR 0013).** Two coexisting pipelines selected by `make --pipeline {director-loop, chain}`
(default `director-loop`). Shape of the chain:
`creative direction → { broll, motion-graphics, text hook } (parallel) → prep → Composer → SFX → render`.

**Module 1 — Pipeline strategy seam.** Refactor the existing `Pipeline` so the shared front half
(ingest → transcribe → ideal-cuts) stays in `Pipeline` and the back half is delegated to a strategy.
`DirectorLoopStrategy` wraps today's DirectorLoop path with identical behavior; `ChainStrategy` is new.
Strategy interface: takes the front-half outputs (transcript + word-timings, ideal cuts, host track,
brand kit, brief) and returns a `Composition` (the existing render/compile tail is shared after the
strategy). The fork seam is after ideal-cuts.

**Module 2 — ChainStrategy.** Orchestrates the fixed order. Runs creative direction first (→ BeatPlan,
forced on); then broll, motion-graphics, and text hook **in parallel** (broll + MG consume the beats
needing visuals and return beat-keyed assets per ADR 0012; text hook consumes the creative concept);
barrier; then prep; then Composer; then SFX. Owns the per-stage **failure policy** (below). No prose
scratchpad — stages pass typed objects.

**Module 3 — Prep step (deep, pure).** `prep(beat_plan, assets, word_timings) ->
list[(Beat{+resolved_span_s}, Asset|None)]`. Two deterministic lookups: (a) zip each beat to its asset
by `beat_id` (missing → `None`); (b) resolve each beat's word-index `transcript_span` to
`[start_s, end_s]` from the transcript word-timings. No model. Output is the Composer's input bundle
(plus hook proposal, host track, brand kit passed through).

**Module 4 — Composer.** `compose(bundle) -> Composition`. A single **no-tools Opus 4.8 Claude Code
SDK** call. Emits a **Composition** directly at the Composition layer (never a kernel op; ADR 0008
holds). LLM-decided placement and gap-fill; decides region/layout/treatment only — the bundle already
fixes which asset and what time-span. Post-generation: run the role-check predicate (Module 5) and the
IR validator; on violation/failure, re-prompt the same call with the errors appended, **bounded**
retries; exhausting retries is a fatal Composer failure. Knowingly opts out of ADR 0012 `execute()`
for the chain only.

**Module 5 — Role-check predicate (deep, pure).** `wrong_role_backfill_violations(composition, beats)
-> list[violation]`. For every placed asset, the role of the beat it was generated for
(`asset.beat_id → beat.role`) must equal the role of the beat occupying the span it landed on. Any
mismatch is a violation. Pure function over the emitted Composition + the BeatPlan; drives the
Composer re-prompt.

**Module 6 — Worker callable seam.** Workers are already reachable as plain `(inputs) -> proposal`
callables via `dispatch.py`; the loop's `_dispatch_worker` is an adapter that adds budget-tracking,
scratchpad writes, and asset registration. Formalize the callable as the shared seam so `ChainStrategy`
calls it directly. The ADR 0012 proposal-shape tightening (creative direction → BeatPlan; broll/MG →
beat-keyed assets; `NewAsset` gains `beat_id`) is a prerequisite and is already scheduled by ADR 0012.

**Module 7 — ChainConfig + CLI.** `--pipeline {director-loop, chain}` (default `director-loop`) and a
general `--tot` flag (applies to both pipelines; flips both ToT-capable workers — creative direction,
text hook — which are Gemini-only per ADR 0011). `--tot` without Gemini wiring errors clearly rather
than falling back. `ChainConfig` keeps `tot_enabled` per-worker so finer isolation needs no new CLI.

**Failure policy (in ChainStrategy).**

| Stage | On failure |
|---|---|
| creative direction | fatal — `PipelineStageError` |
| broll / motion-graphics | degradable — partial → `None` pairs; total → all-`None` |
| text hook | degradable — no opening overlay |
| Composer | fatal after bounded re-prompt |
| SFX | degradable — silent-SFX video |

All-`None` assets stays degradable: the Composer ships a host-only cut.

**Configuration grid.** director-loop vs chain (topology) × `--tot` on/off (worker depth). BeatPlan is
forced on in the chain (the contract). The director-loop pipeline retains ADR 0012's deterministic
`execute()`; only the chain opts out.

## Testing Decisions

Good tests here assert **external behavior at module seams**, not internals: feed a module typed
inputs, assert the typed output. The two pure modules (prep, role-check) are the highest-value targets
because they encode the determinism guarantees and need no model. Prior art: the existing
`tests/test_compile_ir.py`, `tests/test_validator.py`, and `tests/test_composition.py` show the
fixture-driven "build a small typed input → assert structured output" style; the agent-loop tests
(`tests/test_agent_loop.py`, `tests/test_agent_tools.py`) show stubbed-model patterns for the
LLM-backed cases.

- **Prep step (#3).** Unit tests over hand-built `BeatPlan` + assets + word-timings: (a) a beat with a
  matching asset yields a paired tuple; (b) a beat with no matching `beat_id` yields a `None` pair;
  (c) a word-index span resolves to the correct `[start_s, end_s]` against a known word-timing table;
  (d) role/beat order is preserved in the output list.
- **Role-check predicate (#5).** Unit tests over a hand-built Composition + BeatPlan: (a) an asset
  placed on a same-role span → no violations; (b) an asset placed on a different-role span → exactly
  that violation reported; (c) a correctly placed multi-beat composition → empty. This is the test
  that locks the ADR 0012 wrong-role bug shut.
- **ChainStrategy failure policy (#2).** Tests with stubbed workers: (a) creative-direction failure
  raises `PipelineStageError`; (b) all-`None` assets still reach the Composer and produce a host-only
  cut; (c) text-hook failure degrades (no hook, run continues); (d) SFX failure degrades (video still
  renders).
- **Composer (#4).** Tests with a stubbed model: (a) a Composition that fails the IR validator
  triggers a bounded re-prompt with errors appended; (b) a Composition with a wrong-role placement
  triggers a re-prompt; (c) exhausting retries raises a fatal Composer failure. Assert the re-prompt
  *behavior*, not prompt wording.

## Out of Scope

- Changing the director-loop pipeline's behavior in any way (it must remain byte-for-byte the default).
- Superseding or modifying ADRs 0008/0009/0011/0012; the chain is additive.
- The ADR 0012 proposal-shape work itself (BeatPlan type, `NewAsset.beat_id`, beat-keyed broll/MG) —
  it is a prerequisite tracked under ADR 0012, consumed here.
- Per-worker `--tot` CLI flags (config field exists; finer CLI deferred until needed).
- Any new worker, new asset kind, or kernel/validator change beyond what ADR 0012 already schedules.
- A frontend/UX for choosing pipelines beyond the CLI flag.
- Deterministic-placement (`execute()`) *inside* the chain — explicitly rejected for this pipeline.

## Further Notes

- The chain is an experiment harness as much as a feature: its value is the controlled A/B. Keep the
  workers the single shared variable; resist any chain-specific worker fork.
- The Composer is the one nondeterministic node in an otherwise deterministic pipeline. Everything
  with a ground-truth answer (matching, timing, role identity) is pulled out around it; this is the
  design's organizing principle ("deterministic where there's ground truth, LLM where there's
  judgment") and should guide any future addition.
- ToT workers are Gemini-only (ADR 0011); the Composer is Opus 4.8. Different agents, different model
  homes — no conflict.
