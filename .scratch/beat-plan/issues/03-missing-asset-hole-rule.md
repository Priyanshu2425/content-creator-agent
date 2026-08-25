# Missing-asset beat becomes a named hole filled by a deterministic rule

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

When a beat's asset failed to generate (e.g. a 429 mid-generation), the execute phase must treat it as
a **named hole** and fill it by a deterministic rule — punch-in on a neighbouring asset, host A-roll,
or drop the beat — and **never** by promoting a different-role leftover asset. This closes the silent
wrong-role back-fill that put a warm asset in the resolution slot.

## Acceptance criteria

- [ ] A beat with no asset bound to its `beat_id` is identified as a named hole, not silently skipped.
- [ ] `execute()` fills the hole by a deterministic rule (neighbour punch-in / host A-roll / drop) chosen reproducibly from the surrounding beats.
- [ ] Unit test: a `BeatPlan` where one beat has no matching asset asserts the hole is filled by the rule and that no different-role leftover asset is ever promoted into that slot.
- [ ] Test asserts determinism: same BeatPlan + same partial asset set ⇒ same ops.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
