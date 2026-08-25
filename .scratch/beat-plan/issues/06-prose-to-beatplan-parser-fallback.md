# prose→BeatPlan parser for graceful degradation

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

A parse step that turns a prose beat map into a `BeatPlan`, so a weaker model that fumbles structured
output degrades gracefully — it produces a usable plan rather than failing the run. The parser is the
bridge between a model that emits prose and the typed execute path; it either yields a valid `BeatPlan`
or fails cleanly and explicitly (falling back to the legacy prose path), never producing a malformed
plan that the execute phase then mis-handles.

## Acceptance criteria

- [ ] A `parse_beat_plan(prose) -> BeatPlan` (or equivalent) maps a well-formed prose beat map to a valid `BeatPlan`.
- [ ] Malformed / partial prose yields either a usable degraded plan or a clean, explicit failure — never a malformed `BeatPlan`.
- [ ] Unit test: well-formed prose round-trips to the expected `BeatPlan`; malformed prose asserts the clean-failure / degrade behaviour.
- [ ] The creative-direction worker uses the parser as its fallback when structured output is unavailable.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
