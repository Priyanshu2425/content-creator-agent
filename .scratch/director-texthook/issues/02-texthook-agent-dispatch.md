# TextHookAgent worker + `dispatch_text_hook`

Status: ready-for-agent

## Parent

`.scratch/director-texthook/PRD.md` (Phase 2)

## What to build

Add the **TextHookAgent** worker and wire it into the Director via `dispatch_text_hook` (reusing the
in-loop dispatch + dispatch budget from ADR 0008). The Director dispatches it with the transcript,
goal/audience, brand kit, and an optional **frame-1 still** it renders at dispatch time (no raw
source-frame extraction). The worker reads the transcript for the real payoff, generates ranked
**text-hook candidates** across ≥3 distinct patterns, validates each against the hard constraints
(length, frame-one presence, distinct-from-captions, safe zones, casing, no false claims), and
returns a proposal with a recommended pick — placing nothing. The Director picks one and places it as
a `title` overlay confined to the reserved 0–3s hook window, styled to the brand kit. End result: a
video gets a real on-screen text hook in the opening, distinct from its spoken hook and captions.

## Acceptance criteria

- [ ] The Director dispatches `dispatch_text_hook` with transcript + brand kit + optional frame-1
      still, within the dispatch budget.
- [ ] The worker returns ranked candidates spanning ≥3 patterns, all passing the hard constraints,
      with a recommended pick; it places nothing.
- [ ] Degrades gracefully (single `reinforce` candidate + note) when the transcript has no discernible
      payoff.
- [ ] The Director places the chosen hook via `add_title`, confined to the 0–3s hook window and
      distinct from captions.
- [ ] A fake-`ModelClient` test verifies candidate patterns, constraint passing, and the recommended
      pick.

## Blocked by

- `.scratch/director-restructure/issues/03-in-loop-dispatch-broll-worker.md`
- `.scratch/director-texthook/issues/01-title-overlay-add-title-op.md`
