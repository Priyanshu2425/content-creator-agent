# Per-stage failure policy

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

Make the chain's failure handling explicit (it has no adaptive author to route around a failure).
Classify each stage as **required** (fatal — raises `PipelineStageError` naming the stage) or
**degradable** (logged, run continues with a reduced bundle):

| Stage | On failure |
|---|---|
| creative direction | fatal |
| broll / motion-graphics | degradable |
| text hook | degradable |
| Composer | fatal (after bounded re-prompt) |
| SFX | degradable |

An all-`None` asset bundle (broll *and* MG both totally failed) stays **degradable**: the Composer
ships a host-only talking-head cut (consistent with ADR 0005), not a hard failure.

## Acceptance criteria

- [ ] Creative-direction failure raises `PipelineStageError` naming the stage.
- [ ] Composer failure (after retries) raises `PipelineStageError`.
- [ ] broll/MG, text-hook, and SFX failures degrade and the run continues.
- [ ] All-`None` assets produce a host-only cut, not a failure.
- [ ] Tests cover each required-fatal and each degradable path with stubbed workers.

## Blocked by

- `05-beat-keyed-asset-generators-broll-mg.md`
- `06-text-hook-stage-parallel.md`
- `08-sfx-post-composer-stage.md`
