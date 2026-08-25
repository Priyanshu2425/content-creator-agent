# Walking skeleton: single `broll-image` beat end-to-end behind `VIDEOGEN_BEAT_PLAN_ENABLED`

Status: ready-for-agent
Type: AFK

## Parent

`.scratch/beat-plan/PRD.md`

## What to build

The thinnest complete path through the typed BeatPlan pipeline: creative direction emits a one-beat
`BeatPlan`, the b-roll worker generates against that beat and returns the asset tagged with its
`beat_id`, and the Director's new execute phase places that asset on the beat's transcript span —
deterministically, no description re-match. The whole path sits behind `VIDEOGEN_BEAT_PLAN_ENABLED`
(default **on**); when off, the legacy prose creative-direction path runs unchanged.

This establishes the types, the contract, and the execute seam that slices 02–07 widen. Keep it
minimal: only the `broll-image` asset kind, exactly one beat, no role ordering / hole rule / host
beats yet.

- New `BeatPlan` types module: `BeatPlan` (ordered `Beat`s), `Beat` (`id`, `transcript_span` as
  `[start_word_idx, end_word_idx]`, `role`, `intent`, `asset_spec`), `AssetSpec` (`kind`, brief,
  treatment hints). Frozen, kernel-agnostic (ADR 0001/0002).
- `CreativeDirectionAgent.generate()` return type: prose `str` → `BeatPlan`.
- `NewAsset` gains `beat_id: str | None = None`; `GeneratedSlot` gains `beat_id`. B-roll worker
  receives the beat(s) needing visuals and returns beat-keyed assets.
- `DirectorLoop`: `_register_assets()` keys by `beat_id`; a new "execute beat plan" step runs
  `execute(beat_plan, assets, transcript) -> ops` (word indices → seconds via the transcript the
  Director owns → Scene + region) before reconciliation. Director still authors every kernel op
  (ADR 0008).
- Flag routing in `cli.py` mirroring `VIDEOGEN_TOT_*` but defaulting **on** (unset ⇒ enabled).

## Acceptance criteria

- [ ] `BeatPlan`/`Beat`/`AssetSpec` types exist as frozen dataclasses with no kernel concepts; `transcript_span` is a `(start_word_idx, end_word_idx)` int pair.
- [ ] `CreativeDirectionAgent.generate()` returns a `BeatPlan`; the ToT variant is left for slice 07.
- [ ] B-roll worker accepts beats and returns each `NewAsset` tagged with the originating `beat_id`.
- [ ] `execute(beat_plan, assets, transcript)` is a pure function (no LLM) that resolves the span to a Scene + region and emits the placement op for the bound asset.
- [ ] Unit test: a fake one-beat `BeatPlan` + one stub beat-keyed asset + a stubbed word-indexed transcript asserts the asset lands on the beat's span/region. Mirror `test_tot_controller.py`'s pure-function style and the `_Transcript`/`_Word` stubs from `test_agent_tools.py`.
- [ ] Loop integration test (`ScriptedClient` + a `FakeBrollDispatcher` returning a beat-tagged `NewAsset`): the loop runs the execute phase, registers the asset keyed by `beat_id`, and threads the proposal. Mirror `test_agent_loop.py`.
- [ ] `VIDEOGEN_BEAT_PLAN_ENABLED` unset ⇒ enabled; a falsey value ⇒ legacy prose path runs unchanged.
- [ ] Kernel, validator, and SFX worker are untouched.

## Blocked by

None - can start immediately.
