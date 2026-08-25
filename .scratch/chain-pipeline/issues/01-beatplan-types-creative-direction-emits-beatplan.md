# Minimal BeatPlan: types + creative direction emits one

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline. (Overlaps ADR 0012's scope; this is the minimal
tracer that makes the chain self-contained. See `docs/adr/0012-beat-plan-binds-creative-direction-to-placement.md`.)

## What to build

The thin end-to-end slice that introduces the typed **BeatPlan** so the rest of the chain has a
contract to consume. Define the `Beat` and `BeatPlan` domain types (in domain terms — no kernel
scene/region/op concepts): each `Beat` carries a stable `id`, a `transcript_span` as
`[start_word_idx, end_word_idx]`, a narrative `role` (`world-1` / `world-2` / `climax` /
`resolution` / `cta` / `host-aroll`), a one-line `intent`, and an `asset_spec`
(`kind ∈ {broll-image, broll-video, motion-graphic, host-aroll, stat-viz}` + generation brief +
treatment hints), plus optional `layout_hint` / `emphasis`. Add a `beat_id` field to `NewAsset`.
Make the creative-direction worker able to emit a minimal `BeatPlan` (single-pass is fine) via its
plain callable seam. `host-aroll` beats carry no generation brief.

## Acceptance criteria

- [ ] `Beat` and `BeatPlan` types exist with the fields above; `transcript_span` is word indices.
- [ ] `NewAsset` gains an optional `beat_id`.
- [ ] The creative-direction worker can return a `BeatPlan` from its callable seam.
- [ ] A `host-aroll` beat is representable with no generation brief.
- [ ] Unit tests construct a `BeatPlan` and assert the shape round-trips.

## Blocked by

None - can start immediately.
