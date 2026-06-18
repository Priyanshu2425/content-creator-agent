# Caption gallery (standalone preview compositions)

Status: ready-for-agent

## Parent

`.scratch/caption-library/PRD.md`

## What to build

The preview surface a future frontend picker will consume: one standalone Remotion composition per
caption renderer, so each visual can be viewed in isolation with representative sample props.

Register a gallery composition per renderer (at minimum `generic` and `highlight-box`) in `Root.tsx`,
alongside the existing `stat_viz` / `motion_graphics` compositions and following the same pattern:
simple props (sample words/timings + the renderer's params), with duration derived from `fps` +
`duration_s` via the established metadata helper. The compositions reuse the exact same caption
renderer components the IR render path uses — no duplicated visual code.

This slice bypasses the IR; it exists purely so each library entry is independently previewable.

## Acceptance criteria

- [ ] Each registered caption renderer has a standalone gallery composition in `Root.tsx` with representative sample props.
- [ ] Gallery compositions reuse the same renderer components as the IR path (no duplicated visual logic).
- [ ] Composition duration derives from `fps` + `duration_s` via the shared metadata helper, matching the `stat_viz`/`motion_graphics` convention.
- [ ] Each gallery composition renders its caption visual standalone (verified in the Remotion preview / via a still).

## Blocked by

- `.scratch/caption-library/issues/01-caption-style-registry-migrate-existing.md`
- `.scratch/caption-library/issues/02-highlight-box-renderer.md`
