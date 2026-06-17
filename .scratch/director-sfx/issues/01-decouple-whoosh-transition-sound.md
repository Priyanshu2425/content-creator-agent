# Decouple the whoosh transition's built-in sound (visual-only)

Status: ready-for-agent

## Parent

`.scratch/director-sfx/PRD.md` (Phase 3)

## What to build

Make the kernel `whoosh` **transition** purely visual (ADR 0009). Remove its built-in whoosh SFX
accent from the kernel/compile path so the transition renders as a hard visual smash-cut with **no
audio node**. This is the prerequisite that lets the SFXAgent become the single SFX authority without
double-firing a whoosh on a transition cut. The slice is verifiable on its own: a composition with a
`whoosh` transition renders silently at that boundary.

## Acceptance criteria

- [ ] A `whoosh` transition compiles to a visual cut with **no** SFX audio node.
- [ ] No code path emits a whoosh sound from a transition anymore.
- [ ] Snapshots are updated to pin the decoupled (silent) whoosh transition.
- [ ] The change is recorded under ADR 0009; the transition's visual behavior is otherwise unchanged.

## Blocked by

- `.scratch/director-restructure/issues/01-rename-authoring-to-director.md`
