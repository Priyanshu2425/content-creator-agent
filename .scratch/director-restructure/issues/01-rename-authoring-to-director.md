# Rename the authoring agent to Director (no behavior change)

Status: ready-for-agent

## Parent

`.scratch/director-restructure/PRD.md` (Phase 1)

## What to build

Rename the authoring agent to the **Director** throughout: the loop, its system prompt, and all
references, without changing any behavior. The Director still authors the Composition by calling one
validated Builder op per turn, still runs the submit-render gate, and is still wrapped by the
describe stage and the GeminiReview finalization bookend. This is the foundational rename that every
other slice builds on (governed by ADR 0008); it should be a pure refactor that leaves the rendered
output identical for the same input.

## Acceptance criteria

- [ ] The authoring loop/agent is renamed to Director across code, prompt, and references; no stray
      "authoring agent" naming remains in the touched surface.
- [ ] The pipeline runs end-to-end and produces a video for an unchanged input.
- [ ] The submit-render gate, describe stage, and GeminiReview bookend are unchanged in behavior.
- [ ] Existing loop/CLI tests pass (updated only for the rename, not for behavior).

## Blocked by

- None — can start immediately.
