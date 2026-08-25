# The chain pipeline: a fixed-order alternative to the Director loop

Status: Accepted

A second, **coexisting** pipeline runs alongside the Director-loop pipeline (ADR
[0008](./0008-director-dispatches-workers-in-loop.md)) and is selected per run from the CLI. Where
the Director loop *pulls* workers on demand (the model decides dispatch), the **chain pipeline** runs
workers in **fixed order** and a terminal **Composer** agent emits the Composition directly. The two
share the front half and the same worker code; they fork only on *how authoring happens*. The chain
is the experiment: hold the workers constant, vary the topology, A/B the result.

```
ingest → transcribe → ideal-cuts        # shared front half
   └─ strategy fork ─┐
director-loop:  → DirectorLoop (pulls workers on demand) → render        # ADR 0008, default
chain:          → creative direction → { broll, motion-graphics, text hook }
                → prep (zip + resolve spans) → Composer → reconcile (captions + animate stills) → SFX → render
```

## Context — why

ADR 0008 is a deliberate, hard-to-reverse bet on an adaptive Director. ADR
[0012](./0012-beat-plan-binds-creative-direction-to-placement.md) then made placement *deterministic*
inside that loop (a typed `BeatPlan` + `execute(beat_plan, assets) -> ops`) and ADR
[0011](./0011-tot-worker-variant-deliberates-inside-the-worker.md) added deliberating ToT worker
variants. Those pieces invite a different question: if the workers already emit a typed plan and typed
beat-keyed assets, is the Director's *adaptive dispatch* still earning its cost — or would a fixed
order plus a single integrator produce an equal-or-better video more simply and more testably?

You cannot answer that by rewriting the Director — that throws away the loop's machinery and makes the
comparison impossible. You answer it by building the alternative **next to** the loop, sharing the
workers so the only variable is the topology.

## Decision

1. **Two coexisting pipelines, CLI-selected.** `make --pipeline {director-loop, chain}`, default
   `director-loop` (no existing run changes). One `Pipeline` owns the shared front half
   (ingest → transcribe → ideal-cuts); a **strategy** seam at the fork picks `DirectorLoopStrategy`
   (default) or `ChainStrategy`. Each strategy owns its back half fully.

2. **Fixed order, no adaptive dispatch.** The chain runs creative direction first, then **broll,
   motion-graphics, and text hook in parallel** (all consume the BeatPlan; text hook also consumes the
   creative concept; none block each other), then the Composer, then SFX. The pipeline decides
   dispatch, not the model — that is the whole point of the bet, and what keeps the A/B against the
   loop honest.

3. **The Composer is the chain's terminal agent — not the Director.** A single **no-tools Opus 4.8
   Claude Code SDK** call that emits a **Composition directly** (Composition-layer authoring, above
   the kernel — it never authors a kernel op, so ADR 0008's "Director is the only kernel-op author"
   holds literally). It does **LLM-decided placement**, knowingly **opting out of ADR 0012's
   deterministic `execute()`** *for this pipeline only*. Validation is the IR validator on the
   compiled output plus a bounded re-prompt on failure (replacing the loop's per-op validation).

4. **Determinism where there is ground truth; the LLM only where there is judgment.** A deterministic
   **prep** step (no model) runs before the Composer and does two lookups: (a) **zip** each beat to
   its asset by `beat_id` (a missing asset surfaces as an explicit `None` pair), and (b) **resolve**
   each beat's word-index `transcript_span` to concrete `[start_s, end_s]` from the transcript
   word-timings. The Composer is handed time-anchored `(Beat, Asset|None)` pairs and decides only
   *region / layout / treatment / gap-fill* — never *which asset* or *what timestamp*.

   A symmetric deterministic **reconcile** step runs *after* the Composer for the corrections that are
   likewise pure functions of ground truth, not judgment: (a) fill the **base captions** track from
   the transcript word-timings in the brand kit's caption style (a model emitting every word-timed
   caption would be voluminous and drift), and (b) **animate** any still held past the static-image
   limit with a slow zoom — animate, never shorten, since the voiceover master clock fixes spans. This
   is why the chain's first runs shipped dead stills and no captions: those behaviours belong in
   deterministic code, not the LLM, and the reconcile step is where they live.

5. **The one diagnosed bug stays nailed shut.** The Composer's prompt carries an inviolable rule —
   *never place an asset on a beat whose `role` differs from the asset's source-beat role* (the exact
   ADR 0012 wrong-role back-fill failure). Because beats are role-typed and assets are beat-keyed, the
   property is checkable on the emitted Composition; it is asserted post-hoc and re-prompted on
   violation.

6. **Workers are shared, called directly.** The chain invokes the *same* `dispatch.py` worker
   callables the loop dispatches — through their plain `(inputs) -> proposal` seam, not the dispatch
   *tool* wrapper. So a worker improvement helps both pipelines and the A/B compares topology, not two
   broll implementations. The coordination channel is **typed objects only** — no prose scratchpad
   (the scratchpad's prose re-interpretation is the named root cause in ADR 0012; it stays a
   director-loop mechanism).

7. **SFX is reused unchanged.** A fixed post-Composer stage: SFXAgent (ADR
   [0009](./0009-sfxagent-single-sfx-authority.md)) reads the near-final Composition and **layers
   sound onto it** (Composer owns structure, SFX owns sound). No-ops cleanly when there is nothing to
   score.

8. **ToT is a knob, default off.** `tot_enabled` stays per-worker config (creative direction,
   text hook — the only ToT-capable workers, Gemini-only per ADR 0011). A single `--tot` CLI flag
   flips both; it is a *general* flag (meaningful on both pipelines) and errors clearly without Gemini
   wiring rather than silently falling back.

9. **Explicit per-stage failure policy** (the chain has no adaptive author to route around a failure):

   | Stage | On failure |
   |---|---|
   | creative direction | **fatal** — `PipelineStageError` (no BeatPlan ⇒ nothing downstream) |
   | broll / motion-graphics | **degradable** — partial → `None` pairs; total → all-`None`, Composer ships a host-heavy cut |
   | text hook | **degradable** — no opening overlay is a lesser video, not a broken one |
   | Composer | **fatal** after bounded re-prompt — it *is* the artifact |
   | SFX | **degradable** — sound is enhancement; a silent-SFX video still renders |

   An all-`None` asset bundle stays **degradable**: the Composer produces a host-only talking-head
   cut (consistent with ADR [0005](./0005-talking-head-first-kickoff.md)) rather than hard-failing.

## Considered Options

- **Replace the Director loop** (supersede ADR 0008) — rejected: the loop is hard-to-reverse and
  well-justified, and discarding it makes the very comparison the chain exists to run impossible. The
  chain coexists; it supersedes nothing.
- **Chain Director keeps dispatch tools for SFX/MG** — rejected: smuggles the loop's nondeterminism
  back in and confounds the A/B. SFX is a fixed post-stage; MG is a pre-Composer generator (it emits
  beat-keyed assets the Composer must see, so it cannot follow the Composer).
- **Deterministic placement (`execute()`) + LLM reconciliation in the chain** — viable and keeps ADR
  0012 intact, but rejected *for this pipeline* in favour of a single Composer call that places via
  LLM. The bet is explicitly that Opus 4.8 + beat-keyed, time-anchored, role-guarded inputs places
  well enough without the deterministic binding. The director-loop pipeline keeps `execute()`.
- **Forked chain-specific workers** — rejected: confounds the A/B (different topology *and* different
  workers) and doubles maintenance. Workers are the controlled variable.
- **Advisory prose scratchpad in the chain** — rejected: reintroduces the ADR 0012 drift channel and
  gives the Composer two sources of truth. Typed fields (e.g. `Beat.intent`) carry rationale instead.

## Consequences

- **ADRs 0008, 0009, 0011, 0012 all hold.** The chain is additive and scoped: it *opts out* of ADR
  0012's deterministic placement for its own runs only; in the director-loop pipeline 0012 is
  unchanged. No ADR is superseded.
- **The worker callable seam becomes load-bearing.** Workers must expose a tool-independent
  `(inputs) -> proposal` callable (they already do via `dispatch.py`); the loop's dispatch-tool
  wrapper is an adapter over it. This is better design regardless of the chain.
- **A new testable surface.** The deterministic prep step (`zip` + span-resolution) is unit-testable
  in isolation; the chain's structure (fixed order, typed passing, post-hoc role-check) gives clear
  seams the loop's free-form authoring lacks. The Composer itself is the one nondeterministic node.
- **A clean experiment grid.** director-loop vs chain (topology) × ToT on/off (worker depth), with
  BeatPlan forced on in the chain (it is the contract — a chain run without it is incoherent).
- **Surface changes:** a `--pipeline` CLI flag and `Pipeline` strategy seam; a `ChainStrategy`; a
  `Composer` agent; a deterministic prep step and a deterministic reconcile step (base captions +
  animate stills); a `ChainConfig` (per-worker `tot_enabled`). The kernel,
  validator, and existing workers are untouched beyond the proposal-shape tightening ADR 0012 already
  schedules.

## Resolved questions

- **Replacement or coexisting?** Coexisting, CLI-selected. Default stays `director-loop`.
- **Director's role in the chain?** None — the chain has no Director. Its terminal agent is the
  **Composer**, a distinct agent. The Director belongs to the loop pipeline.
- **Why LLM placement (drop `execute()`)?** A deliberate, scoped bet for this pipeline: test whether a
  strong model with typed, time-anchored, role-guarded inputs places as well as the deterministic
  binding. The loop keeps `execute()` as the safety baseline.
- **Where does motion-graphics sit?** Pre-Composer, alongside broll — it is an asset generator whose
  beat-keyed output the Composer must see. Generators feed the Composer; only SFX follows it.
- **Text hook ordering?** Parallel with the asset generators, after creative direction (it depends on
  the creative concept, not on generated assets).
- **Scratchpad?** None in the chain — typed passing only.
