# Behavioral pacing reconciler over the Resolver timeline

Status: ready-for-agent

## Parent

`.scratch/director-restructure/PRD.md` (Phase 1)

## What to build

Add a pure **Pacing reconciler** module and wire it into the Director's behavior. Given the Resolver
timeline + pacing budget + brand-kit safe zones, it returns a report of **static gaps**,
**competing-overlay collisions**, and **safe-zone violations**. The Director acts on the report with
existing Builder ops: insert `zoom` punch-ins (within the brand-kit motion range) to fill gaps, drop
the weaker of two changes within the minimum change interval, keep the 0–3s hook window clear of
competing overlays, and emit a self-computed pacing report in its notes. Pacing stays Director
behavior — the kernel validator is unchanged (machine enforcement is the deferred Phase 4).

## Acceptance criteria

- [ ] The reconciler returns gaps, collisions, and safe-zone violations for a given timeline; an empty
      report when the timeline is within budget.
- [ ] The Director fills a static gap with a `zoom` punch-in and de-duplicates near-collisions.
- [ ] The 0–3s hook window is kept clear of competing overlays.
- [ ] A self-computed pacing report appears in the Director's notes; the kernel validator is unchanged.
- [ ] Unit tests cover the pure reconciler (gap/collision/safe-zone detection; empty-report case) per
      the PRD test scope.

## Blocked by

- `.scratch/director-restructure/issues/02-brand-kit-from-brand-profile.md`
- `.scratch/director-restructure/issues/04-fold-idealcuts-timeline-skeleton.md`
