# PRD: Director restructure — Phase 3 (SFXAgent + single SFX authority)

Status: ready-for-agent

> Scope note: **Phase 3** of the Director restructure. Depends on Phase 1
> (`.scratch/director-restructure/PRD.md`) — the Director, in-loop dispatch, and brand kit (which
> already carries the sfx palette + density budget tokens). Phase 2 is independent and may land
> before or after.

## Problem Statement

Sound effects exist today but are split across two uncoordinated mechanisms. `AudioDeciderAgent` runs
as a fixed post-authoring stage that annotates every scene cut with a sound, and — separately — the
kernel's `whoosh` **transition** bundles its own whoosh SFX accent. Two authorities means a whoosh
transition plus an AudioDecider whoosh can double-fire on the same cut, and neither is dispatched by
the agent that owns the video's cross-layer consistency. SFX placement is also not a decision the
Director can make in context (it runs blind, after authoring, with no view of the master timeline as
an event stream).

## Solution

Recast `AudioDeciderAgent` as the **SFXAgent** worker, dispatched in-loop by the Director, and make it
the **single SFX authority**:

- the Director owns an **event timeline** — it classifies the assembled composition's meaningful
  moments (hook, scene_change, reveal, graphic_pop, caption_emphasis, list_item, cta) into a typed
  event stream and passes it to the worker;
- the **SFXAgent** maps events to the brand-kit **sfx palette** within the **density budget**, doing
  only the emphasis-selection and conflict-resolution judgment, and returns a placement proposal;
- the `whoosh` **transition loses its built-in sound** — it becomes a purely *visual* smash-cut, and
  any whoosh *sound* is placed by the SFXAgent. One authority, no double-fire.

v1 stays cut-bound (SFX binds to scene cuts via the existing `scene.audio` path that already renders)
and uses the three real sounds (`click`/`whoosh`/`dramatic_whoosh`).

## User Stories

1. As a creator, I want sound effects only on genuinely meaningful moments, so that my video does not
   read as amateur template-spam where every cut beeps.
2. As a creator, I want SFX to sit under my voice, so that a sound never fights the dialogue.
3. As a creator, I want a consistent sound identity across the video, so that the SFX feel designed
   rather than random.
4. As a creator, I want a whoosh transition to not double up with a whoosh sound effect on the same
   cut, so that the moment is not over-sounded.
5. As the Director, I want to classify the assembled composition into a typed event timeline, so that
   the SFXAgent receives meaningful moments rather than raw cuts.
6. As the Director, I want to dispatch the SFXAgent after I have placed the visuals, so that the event
   timeline reflects the real master timeline (SFX is effectively the last worker).
7. As the Director, I want to inject the sfx palette and density budget from the brand kit, so that
   the worker draws only from the locked sound kit and stays inside the budget.
8. As the Director, I want the SFXAgent's placements applied via the existing `scene.audio` path, so
   that SFX renders through the already-wired audio IR node.
9. As the Director, I want to be the only SFX authority, so that the `whoosh` transition no longer
   emits its own sound and cannot conflict with a placed SFX.
10. As the Director, I want to skip the SFXAgent for a video that needs no SFX, so that silence stays
    the default when nothing meaningful needs marking.
11. As the SFXAgent worker, I want to consider only the events in the timeline, so that I never add a
    sound at a cut that is not a meaningful event.
12. As the SFXAgent worker, I want to map each event type to a palette key deterministically, so that
    the routine part of the job is consistent.
13. As the SFXAgent worker, I want to keep only the high-impact `reveal`/`caption_emphasis`
    candidates, so that restraint — not coverage — is the default.
14. As the SFXAgent worker, I want to enforce the density budget locally (minimum gap, max per 10s, no
    overlap), so that placements never cluster or stack.
15. As the SFXAgent worker, I want to log every event I chose not to sound, so that my restraint is
    auditable.
16. As the SFXAgent worker, I want to place nothing and note it when no palette entry fits, so that I
    never invent or fetch an off-kit sound.
17. As the SFXAgent worker, I want to return a placement proposal and certify nothing, so that the
    Director stays the authority that reconciles global density.
18. As the kernel, I want the `whoosh` transition to render as a visual cut with no audio node, so
    that the transition and the SFX layer are fully decoupled.
19. As a maintainer, I want the event-timeline classification extracted as a pure module, so that
    composition → typed events is tested without an LLM.
20. As a maintainer, I want the SFXAgent tested with a fake `ModelClient`, so that its mapping,
    emphasis pass, and budget enforcement are verified deterministically.
21. As a maintainer, I want snapshot coverage updated so a `whoosh` transition no longer emits an
    audio IR node, so that the decoupling is pinned.

## Implementation Decisions

- **SFXAgent recasts `AudioDeciderAgent`.** Same fundamental job (decide a sound per meaningful
  moment), now dispatched in-loop via `dispatch_sfx` (reuses Phase 1's dispatch + budget) instead of
  running as a fixed post-authoring stage.
- **The Director owns the `event_timeline`.** The deterministic cut/moment classification currently
  living inside `AudioDeciderAgent` moves into a pure **event-timeline builder** the Director runs over
  the assembled composition, producing typed events (`hook`, `scene_change`, `reveal`, `graphic_pop`,
  `caption_emphasis`, `list_item`, `cta`). The worker no longer infers event types — it receives them.
- **SFXAgent does only the thin creative layer.** Event-type → palette mapping is deterministic;
  millisecond → frame conversion via `meta.fps` is deterministic. The worker decides only
  emphasis-selection (keep the high-impact `reveal`/`caption_emphasis`, drop the rest) and
  conflict-resolution (keep the single most meaningful of a tight cluster).
- **Single SFX authority; decouple the `whoosh` transition's sound.** The `whoosh` transition becomes
  visual-only — its built-in SFX accent is removed from the kernel/compile path. Any whoosh *sound* is
  now an SFXAgent placement. This changes render behavior and existing snapshots and is the
  hard-to-reverse decision of this phase.
- **v1 is cut-bound.** SFX placements bind to scene cuts via the existing `scene.audio` field, which
  already compiles to an audio IR node and renders. Free-timestamp SFX (mid-scene `caption_emphasis`
  not on a cut) needs a new audio-overlay track and is deferred.
- **v1 palette = the three real sounds** (`click`, `whoosh`, `dramatic_whoosh`). The doc's seven-key
  palette (riser/pop/impact/tick/confirm) is deferred until those asset files exist.
- **Budget from the brand kit.** The density budget (`min_gap_ms`, `max_per_10s`, `no_overlap`) and the
  palette are carried on the brand kit (established in Phase 1), so SFX draws from the same locked
  source as every other layer.

## Testing Decisions

- **What makes a good test here:** assert external behavior. For the event-timeline builder, *given a
  composition → the expected typed event stream*. For the worker, *given a scripted fake `ModelClient`
  and an event timeline + palette + budget → a placement proposal that respects the budget and sounds
  only meaningful events*. For the decoupling, *a `whoosh` transition compiles to no audio node*.
- **Modules to test:**
  - **Event-timeline builder** — pure: composition with known cuts/reveals → the expected typed
    events; micro jump-cuts excluded.
  - **SFXAgent** — fake-client test: event-type mapping correct; emphasis pass drops low-impact
    candidates; density budget enforced (gaps ≥ min, ≤ max per 10s, no overlaps); off-kit request →
    places nothing and notes it.
  - **Whoosh decoupling** — snapshot/behavioral: a composition with a `whoosh` transition produces a
    visual cut and **no** SFX audio node.
- **Prior art:** the existing `AudioDeciderAgent` tests (for the event/mapping behavior being recast),
  the IR snapshot tests (`tests/snapshots/*.json`) for the whoosh decoupling, and the fake-`ModelClient`
  agent tests for the worker.

## Out of Scope

- **Free-timestamp SFX** (mid-scene emphasis not on a cut) — needs a new audio-overlay track; later.
- **The seven-key palette** (riser/pop/impact/tick/confirm) — asset files do not exist; later.
- **Music, ducking, loudnorm** — Phase 6; no music exists in the pipeline today.
- **A kernel-enforced global density certifier** — the Director reconciles density behaviorally; a
  machine certifier is out of scope here (and overlaps Phase 4's pacing validator).
- **TextHookAgent / `title` overlay** (Phase 2).

## Further Notes

- This phase is governed by **ADR 0009 — the SFXAgent becomes the single SFX authority and the
  `whoosh` transition loses its built-in sound** — hard to reverse (render behavior + snapshots),
  surprising (a whoosh transition no longer makes a sound), and a real trade-off (single authority vs.
  two convenient-but-drifting mechanisms). The in-loop dispatch this worker uses is governed by ADR
  0008.
- The `sfx_agent_system_prompt` doc is the brainstorming basis for the worker's prompt; its
  "sound marks meaning, not rhythm" principle and the deterministic-vs-decided split carry over, but
  the worker receives the event timeline rather than inferring it, and it certifies nothing.
