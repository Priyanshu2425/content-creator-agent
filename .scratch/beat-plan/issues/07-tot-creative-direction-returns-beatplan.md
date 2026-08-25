# ToT creative-direction variant returns a `BeatPlan`

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

Bring the Tree-of-Thoughts creative-direction variant onto the typed contract:
`CreativeDirectionToTAgent.generate()` returns a `BeatPlan` instead of prose, matching the single-pass
agent (slice 01). The ToT deliberation still happens inside the worker (ADR 0011); only the final
proposal's type tightens. Reuse the prose→BeatPlan parser (slice 06) so a deliberation branch that
emits prose still resolves to a typed plan.

## Acceptance criteria

- [ ] `CreativeDirectionToTAgent.generate()` returns a `BeatPlan`.
- [ ] The ToT search/deliberation behaviour is otherwise unchanged (ADR 0011 holds).
- [ ] The variant reuses the slice-06 parser for branches that produce prose.
- [ ] Test mirrors `test_creative_direction_tot.py`: the winning deliberation output resolves to a valid `BeatPlan`.
- [ ] Both creative-direction agents (single-pass and ToT) are interchangeable behind the dispatch contract.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
- `.scratch/beat-plan/issues/06-prose-to-beatplan-parser-fallback.md`
