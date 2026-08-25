# Creative direction → BeatPlan → Composer (typed passing)

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

Wire the first real worker into the chain and have the Composer place from a BeatPlan — still with no
*generated* assets. `ChainStrategy` calls the creative-direction worker (BeatPlan forced on) through
its plain callable seam, runs the prep step (every pair is `(Beat, None)` since no generators yet,
but spans are resolved to seconds and `host-aroll` beats are present), and hands the Composer
time-anchored pairs. The Composer places `host-aroll` beats on the host track per the BeatPlan's
structure and emits the Composition. Coordination is **typed objects only — no prose scratchpad**.

This slice also formalizes the **worker callable seam**: the chain calls workers directly via their
`(inputs) -> proposal` callable, and the loop's dispatch-tool becomes a thin adapter over the same
code (no behavior change to the loop).

## Acceptance criteria

- [ ] `ChainStrategy` obtains a `BeatPlan` from the creative-direction worker's callable seam.
- [ ] Prep resolves spans to seconds and yields `(Beat, None)` pairs to the Composer.
- [ ] The Composer respects the BeatPlan's beat order/roles (host beats land where the plan reserves).
- [ ] No prose scratchpad is used anywhere in the chain.
- [ ] The director-loop pipeline still works unchanged through the same worker callable.
- [ ] A test with stubbed workers asserts the BeatPlan structure reaches the Composer.

## Blocked by

- `01-beatplan-types-creative-direction-emits-beatplan.md`
- `02-walking-skeleton-chain-pipeline-host-only.md`
- `03-prep-step-zip-and-span-resolution.md`
