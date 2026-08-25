# Beat-keyed asset generators (broll + motion-graphics) in parallel

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

Add the visual asset path. `ChainStrategy` runs the **broll** and **motion-graphics** workers **in
parallel** after creative direction; each receives the beats needing visuals and returns assets
**tagged with their `beat_id`**. The prep step now zips real assets onto their beats (missing ones
stay `None`), and the Composer places the bound assets on their beats' resolved spans. Motion-graphics
runs *before* the Composer (it is a generator the Composer must see), and no-ops cleanly when the
BeatPlan has no stat-viz / motion-graphic beats.

## Acceptance criteria

- [ ] broll and motion-graphics run concurrently (wall-clock ≈ slowest, not sum).
- [ ] Returned assets carry `beat_id`; prep zips them by id.
- [ ] The Composer places each asset on its beat's resolved span.
- [ ] A BeatPlan with no motion-graphic beats produces a clean MG no-op.
- [ ] A test asserts a beat-keyed asset lands on the correct beat's span.

## Blocked by

- `01-beatplan-types-creative-direction-emits-beatplan.md`
- `04-creative-direction-to-composer-typed-passing.md`
