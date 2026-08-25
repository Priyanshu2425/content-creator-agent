# PRD: Typed BeatPlan binds creative direction to placement

Status: ready-for-agent

> Scope note: replaces the **prose creative-direction proposal** with a typed **BeatPlan** (ordered
> **Beats**) that carries a stable **beat id** through asset generation, so the **Director** *executes
> a binding* (asset tagged with beat *B* lands on beat *B*'s span) instead of re-matching assets to
> moments by re-reading text. Architecture is fixed by ADR
> [0012](../../docs/adr/0012-beat-plan-binds-creative-direction-to-placement.md); the Director's
> authorship contract (ADR [0008](../../docs/adr/0008-director-dispatches-workers-in-loop.md)) and the
> ToT worker variants (ADR [0011](../../docs/adr/0011-tot-worker-variant-deliberates-inside-the-worker.md))
> still hold. Glossary terms: *Director*, *Worker*, *Proposal*, *Beat*, *BeatPlan*, *Beat id*,
> *Transcript span*, *Asset spec*, *Creative direction*, *Reconciliation*.

## Problem Statement

A real run (`renders/2026-06-19T19-18-33`) produced a broken narrative arc: warm "world-1" assets
landed in the **resolution** slot, the one resolution asset that *was* generated was registered but
never placed, the brief's payoff never appeared on screen, and several stills were held 1.6–2.4s.

The root cause is that creative intent travels as **prose through a scratchpad** and is re-interpreted
three times — the creative-direction worker writes a prose beat map, the b-roll worker re-interprets
it into image prompts, and the Director re-interprets *both* (prose + each asset's text description) to
choose placements. There is **no machine-readable link** from a beat to the asset that serves it. Each
hop re-derives intent, drift compounds, and when a beat's asset is missing (e.g. a 429 mid-generation)
the Director silently back-fills with a wrong-role leftover. The system prompt already told the model
to stay true to the creative direction and to hold stills ≤1s — it did neither, because **prose
guidance is not an enforceable contract** and there is no test seam to lock the behaviour down.

## Solution

The creative-direction worker emits a typed **BeatPlan** — an ordered list of **Beats** in domain
terms (no kernel scene/region/op concepts). Each Beat carries a stable `id`, a `transcript_span` (the
*when*, as word indices), a narrative `role`, a one-line `intent`, and an `asset_spec`. Asset-
generating workers receive the beats that need visuals and return each asset **tagged with its
`beat_id`** — the asset↔beat link is an explicit lookup, never a description re-match.

The Director then runs a new **execute** phase: it maps each beat's `transcript_span` to a Scene +
region and places the bound asset there in role order — **deterministically** — *before* doing the
reconciliation work only it can (pacing certification, gap-fill punch-ins, collision/occlusion, brand
enforcement, captions, SFX, host-A-roll intercut, `finish`). A missing-asset beat becomes a **named
hole** filled by a deterministic rule (punch-in on a neighbour, host A-roll, or drop the beat) — never
by promoting a different-role leftover. The whole feature sits behind `VIDEOGEN_BEAT_PLAN_ENABLED`
(default **on**), with the legacy prose path retained as fallback.

## User Stories

1. As a video creator, I want the creative direction's payoff beat to actually appear on screen, so
   that the video delivers the brief's promise.
2. As a video creator, I want warm "world-1" assets to land in the world-1 section and resolution
   assets in the resolution, so that the narrative arc reads correctly.
3. As a video creator, I want the talking head reserved at the opening claim and CTA, so that the
   product stays talking-head-first instead of dumping the host into the tail.
4. As a video creator, I want static images held no longer than ~1s without motion, so that the video
   never feels dead on screen.
5. As the Director, I want each generated asset tagged with the beat it serves, so that I place it by
   lookup instead of guessing from its text description.
6. As the Director, I want to map a beat's transcript span to a Scene and region deterministically, so
   that placement is reproducible and testable.
7. As the Director, I want a beat whose asset failed to generate to be a named hole, so that I fill it
   by an explicit rule rather than silently back-filling a wrong-role leftover.
8. As the Director, I want to keep authoring every kernel op and owning cross-layer reconciliation, so
   that ADR 0008 still holds and the BeatPlan is only a richer proposal.
9. As the Director, I want to override or drop a beat when reconciliation demands it, so that the
   BeatPlan stays advisory, not binding.
10. As the creative-direction worker, I want to emit Beats in domain terms with no kernel concepts, so
    that I stay kernel-agnostic per ADR 0001/0002.
11. As the creative-direction worker, I want to reserve `host-aroll` beats (opening claim + CTA) that
    carry no generation brief, so that host time is reserved up front without inventing footage.
12. As the b-roll worker, I want to receive the specific beats that need visuals, so that I generate
    against a typed spec instead of re-interpreting prose.
13. As the b-roll worker, I want to return each generated asset tagged with its `beat_id`, so that the
    Director binds it without re-matching.
14. As the motion-graphics worker, I want the same beat-driven input/output contract as b-roll, so that
    every generated asset is beat-keyed uniformly.
15. As a developer, I want `execute(beat_plan, assets, transcript) -> ops` to be a pure deterministic
    function, so that I can unit-test placement with a fake BeatPlan and stub assets.
16. As a developer, I want a test asserting each asset lands on its beat's span/region with role order
    preserved, so that the diagnosed misplacement bug is locked down.
17. As a developer, I want a test asserting a missing-asset beat is handled by the hole rule, so that
    silent wrong-role back-fill can never regress.
18. As a developer, I want a test asserting host beats reserve time and bind the existing host track
    (not a generated asset), so that the "host in the tail" failure stays fixed.
19. As an operator, I want a `VIDEOGEN_BEAT_PLAN_ENABLED` flag defaulting on, so that the typed path is
    the default while I can fall back to the legacy prose agent if needed.
20. As an operator running a weaker model, I want a prose→BeatPlan parse step, so that a model that
    fumbles structured output degrades gracefully instead of failing the run.
21. As a maintainer, I want the kernel, validator, and SFX worker untouched, so that the change stays
    contained to the creative-direction → generation → placement path.
22. As a maintainer, I want transcript spans expressed as word indices, so that beat timing survives
    re-timing of the underlying audio.

## Implementation Decisions

**New `BeatPlan` types module.** Frozen dataclasses in domain terms, kernel-agnostic.
- `BeatPlan` = ordered `tuple[Beat, ...]`.
- `Beat`: `id: str` (stable); `transcript_span: tuple[int, int]` = `[start_word_idx, end_word_idx]`
  into the transcript the Director already owns; `role` ∈ {`world-1`, `world-2`, `climax`,
  `resolution`, `cta`, …}; `intent: str` (one line); `asset_spec: AssetSpec`; optional `layout_hint`,
  `emphasis`.
- `AssetSpec`: `kind` ∈ {`broll-image`, `broll-video`, `motion-graphic`, `host-aroll`, `stat-viz`}; a
  generation brief; treatment hints. **`host-aroll` carries no generation brief** — its asset is the
  existing talking-head track, so the beat is a pure placement reservation.

**`execute(beat_plan, assets, transcript) -> ops` — the core new deterministic phase.**
- Resolve each `transcript_span` (word indices → seconds via `manifest.transcript.words`, the Director
  owns the indices→seconds mapping) → Scene + region.
- Bind beat→asset by `beat_id` lookup; place in **role order**.
- `host-aroll` branch binds the existing host track instead of looking up a generated asset.
- Missing-asset beat → named hole, filled by deterministic rule (neighbour punch-in / host A-roll /
  drop). Never promote a different-role leftover.
- Pure function, no LLM. Runs *before* reconciliation.

**`CreativeDirectionAgent.generate()` return type: prose `str` → `BeatPlan`.** Same change to the ToT
variant `CreativeDirectionToTAgent.generate()`. A **prose→BeatPlan parser** provides the graceful-
degrade path for weaker models.

**Asset workers become beat-driven and beat-keyed.** `GenerateBrollAgent.run()` (and motion-graphics)
receive the beats needing visuals instead of a prose `ideal_cuts_plan`; `GeneratedSlot` gains
`beat_id`; `NewAsset` gains `beat_id: str | None = None` (optional — SFX and other non-beat workers
leave it `None`).

**Director loop gains an execute phase.** `_register_assets()` keys registered assets by `beat_id`; a
new "execute beat plan" step runs the `execute()` function before reconciliation. Authorship does not
move — the Director still emits every kernel op (ADR 0008); the BeatPlan is a richer *proposal* it may
override or drop.

**Flag wiring.** `VIDEOGEN_BEAT_PLAN_ENABLED` (truthy ∈ {1,true,yes,on}), routed in `cli.py` mirroring
the `VIDEOGEN_TOT_*` pattern — but **defaulting on** (unset ⇒ enabled), unlike `tot_enabled`. Off ⇒
legacy prose creative-direction agent.

**Untouched:** kernel, validator, SFX worker. The `STATIC_IMAGE_TOO_LONG` validator warning already
landed independently and remains the static-hold backstop on both paths.

## Testing Decisions

A good test asserts **external behaviour, not implementation details**: given a BeatPlan and assets,
assert where things land and what ops result — not how the function loops. Prior art: `test_tot_controller.py`
(pure search over stubbed generators/evaluators), `test_agent_loop.py` (`ScriptedClient` +
`FakeBrollDispatcher`, assert routing + `builder.composition.assets`), `test_agent_tools.py`
(`_Transcript`/`_Word` stubs, kernel-validated assertions).

Modules to test (all four selected):

- **`execute()` placement** *(highest value — the regression seam)*. With a fake BeatPlan + stub
  beat-keyed assets + a stubbed word-indexed transcript: assert each asset lands on its beat's
  span/region; assert role order is preserved; assert a missing-asset beat is filled by the hole rule
  and **never** by a different-role leftover. Mirror `test_tot_controller.py`'s pure-function style.
- **`BeatPlan` types + prose→BeatPlan parser**. Assert a well-formed BeatPlan round-trips/validates;
  assert malformed prose still yields a usable plan or a clean, explicit failure (graceful degrade).
- **Director execute phase (loop)**. Integration via `ScriptedClient` + a `FakeBrollDispatcher`
  returning beat-tagged `NewAsset`s: assert the loop runs the execute phase, registers assets keyed by
  `beat_id`, and threads the proposal. Mirror `test_agent_loop.py`.
- **`host-aroll` reservation**. Assert host beats (opening claim + CTA) reserve time up front and bind
  the **existing host track**, not a generated asset — locking the diagnosed "host in the tail" bug.

Use the `_Transcript`/`_Word` stubs from `test_agent_tools.py` for a lightweight word-indexed
transcript seam.

## Out of Scope

- Any change to the kernel, the validator, or the SFX worker.
- Merging creative-direction and generation into one worker — **rejected** in ADR 0012; the b-roll
  worker stays the generator and the Director passes it the beats.
- Emitting kernel ops (scenes/regions/timestamps) from the creative worker — rejected; the worker
  stays kernel-agnostic and the Director remains the author.
- Transcript spans in absolute seconds — rejected in favour of word indices.
- New `host-aroll` generation — host beats reserve placement of the existing host track only; no
  footage is generated for them.
- Retiring the legacy prose creative-direction agent — it stays as the `beat_plan_enabled=off` fallback.

## Further Notes

- The architectural payoff is testability: `execute(beat_plan, assets) -> ops` is the deterministic
  seam the pure-LLM placement path lacked (the open finding from the diagnosis).
- Rollout deliberately diverges from `tot_enabled`: BeatPlan defaults **on** because the typed path is
  the intended default behaviour, with prose retained only as a fallback for weaker models.
- All four open questions in ADR 0012 are now resolved (word indices; host-aroll included now;
  b-roll stays generator; flag defaults on) — the ADR is **Accepted**.
