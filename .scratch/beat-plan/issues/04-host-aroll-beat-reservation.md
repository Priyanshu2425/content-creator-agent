# `host-aroll` beat reservation binds the existing host track

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

Add the `host-aroll` asset kind and reserve host (talking-head) time up front as first-class beats.
Unlike every other kind, a `host-aroll` beat carries **no generation brief** — its "asset" is the
existing talking-head track, so the beat is a pure placement reservation (span + intent). The execute
phase binds a `host-aroll` beat to the host track instead of looking up a generated asset. By default
the BeatPlan reserves host beats at the opening claim and the CTA, keeping the product talking-head-
first and closing the diagnosed "host dumped in the tail" failure.

## Acceptance criteria

- [ ] `AssetSpec.kind` includes `host-aroll`; a `host-aroll` beat validates with no generation brief.
- [ ] `execute()` has a branch that binds a `host-aroll` beat to the existing host track rather than a generated asset, placing it on the beat's span.
- [ ] The creative-direction worker reserves host beats by default at the opening claim and CTA.
- [ ] Unit test: a `BeatPlan` with host beats asserts host time is reserved up front and that the host track (not a generated asset) is bound — locking the "host in the tail" bug.
- [ ] No host footage is generated for a `host-aroll` beat.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
