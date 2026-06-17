# Fold IdealCuts into the Director's timeline skeleton

Status: ready-for-agent

## Parent

`.scratch/director-restructure/PRD.md` (Phase 1)

## What to build

Dissolve the standalone IdealCuts stage into the Director. Add a pure **Timeline skeleton** module
that merges the cross-layer change record — hard-cut plan, caption cadence, and the reserved 0–3s
hook window — into a single sorted, de-duplicated change list the Director uses for cut planning and
(later) pacing. The deterministic merge is pure and testable; the LLM cut-planning becomes part of
the Director's reasoning rather than a separate upstream agent. The pipeline no longer runs IdealCuts
as its own stage.

## Acceptance criteria

- [ ] The standalone IdealCuts pipeline stage is removed; the Director builds the timeline skeleton
      itself.
- [ ] The Timeline skeleton module merges hard cuts + caption cadence + hook window into one sorted,
      de-duplicated change list with the hook window reserved.
- [ ] The pipeline renders end-to-end with cut planning driven from the skeleton.
- [ ] Unit tests cover the pure skeleton-merge (ordering, de-duplication, hook-window reservation) per
      the PRD test scope.

## Blocked by

- `.scratch/director-restructure/issues/01-rename-authoring-to-director.md`
