# Multi-beat role ordering in `execute()`

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

Extend the execute phase from one beat to an ordered `BeatPlan` of many beats, placing each bound
asset in **narrative role order** (`world-1` → `world-2` → `climax` → `resolution` → `cta` → …). This
is the slice that directly fixes the diagnosed misplacement: warm "world-1" assets must land in the
world-1 section and the resolution asset in the resolution slot, by binding through `beat_id` and role
rather than re-reading asset text.

`role` becomes a meaningful ordering key in `execute()`; the creative-direction worker emits beats
spanning the full arc.

## Acceptance criteria

- [ ] `execute()` places every beat's bound asset on its own span, preserving role order across the timeline.
- [ ] Unit test: a multi-beat `BeatPlan` (e.g. world-1, climax, resolution) + stub beat-keyed assets asserts each asset lands on its beat's span/region and that role order is preserved — a world-1 asset never lands in the resolution slot.
- [ ] Test reproduces the diagnosed failure shape (warm asset would have landed in resolution under prose matching) and asserts it no longer does.
- [ ] No change to the Director's authorship or reconciliation responsibilities.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
