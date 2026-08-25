# Motion-graphics worker becomes beat-driven and beat-keyed

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

Bring the motion-graphics worker onto the same beat-driven contract as b-roll: it receives the beats
needing motion-graphic / stat-viz assets and returns each generated asset tagged with its `beat_id`,
so the Director binds it by lookup in the execute phase. This makes every generated asset beat-keyed
uniformly, regardless of which worker produced it.

## Acceptance criteria

- [ ] The motion-graphics worker accepts beats (`asset_spec.kind` ∈ {`motion-graphic`, `stat-viz`}) instead of prose guidance.
- [ ] Each asset it returns is a `NewAsset` tagged with the originating `beat_id`.
- [ ] `execute()` places motion-graphic / stat-viz assets on their beats' spans identically to b-roll assets.
- [ ] Unit/integration test: a `BeatPlan` mixing a `broll-image` beat and a `motion-graphic` beat asserts both assets land on their respective spans via `beat_id` binding.

## Blocked by

- `.scratch/beat-plan/issues/01-walking-skeleton-single-beat-end-to-end.md`
