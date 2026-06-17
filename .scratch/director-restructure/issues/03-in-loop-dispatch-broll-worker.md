# In-loop worker dispatch + dispatch budget, proved with the b-roll worker

Status: ready-for-agent

## Parent

`.scratch/director-restructure/PRD.md` (Phase 1)

## What to build

Add the in-loop **worker dispatch** mechanism (ADR 0008) to the Director loop and prove it
end-to-end by converting the existing `GenerateBrollAgent` into the first dispatchable worker. The
Director's tool surface gains `dispatch_broll` alongside the Builder ops; calling it runs the b-roll
worker (which produces standalone Nano Banana stills + Remotion stat-viz clips and returns a
**shot-list proposal** with placement intent in brand-kit tokens + contributed-change timestamps),
threads the proposal back into the Director's perception, and the Director turns accepted shots into
`fill_region`/`add_overlay` ops. Dispatches draw from a small **separate per-worker dispatch budget**
(recommended ≤2) that does not consume the Builder-op budget; a video with no b-roll moments simply
never dispatches. The Director injects the locked brand kit into the dispatch.

## Acceptance criteria

- [ ] The Director can call `dispatch_broll` mid-loop and receives a shot-list proposal as a tool
      result, threaded into perception.
- [ ] The b-roll worker produces standalone asset clips and returns a proposal only — it does not
      composite (the Director places via Builder ops; ADR 0002 intact).
- [ ] A separate per-worker dispatch budget is enforced; dispatches do not decrement the Builder-op
      budget; at zero budget a dispatch is refused.
- [ ] The Director can skip dispatch entirely for a video with no b-roll moments.
- [ ] The brand kit is injected into the dispatch.
- [ ] Unit test covers dispatch-budget accounting; the dispatch path is exercised via a fake
      `ModelClient` loop test.

## Blocked by

- `.scratch/director-restructure/issues/02-brand-kit-from-brand-profile.md`
