# PRD: Director restructure — Phase 2 (TextHookAgent + `title` overlay)

Status: ready-for-agent

> Scope note: **Phase 2** of the Director restructure. Depends on Phase 1
> (`.scratch/director-restructure/PRD.md`) being landed — the Director, in-loop dispatch mechanism,
> dispatch budget, and brand kit must exist. This phase adds the first net-new worker and the kernel
> support to place its output.

## Problem Statement

A talking-head short carries two hooks aimed at two viewers: the **spoken hook** (the creator's
recorded opening line, for the viewer who already turned sound on) and the **text hook** (an
on-screen headline for the muted scroller and the paused thumbnail). The system produces neither a
text hook nor any way to place one. The kernel has no text overlay at all — overlay types are only
`zoom`/`pan`/`insert`, the Builder ops cannot place a static headline, and a **caption** is the wrong
vehicle (it is transcript-synced, word-by-word animated, and explicitly *not* a title per the
glossary). So the single highest-leverage scroll-stopping element of a short is missing.

## Solution

Add a **TextHookAgent** worker that the Director dispatches in-loop, and the kernel support to place
its output:

- a new additive **`title` overlay** type — a static text headline with start/end, region, z, and a
  brand-kit display-font token — compiling to the IR `TextLayer` that already exists;
- a new **`add_title`** Builder op so the Director places a chosen hook;
- the **TextHookAgent** worker, dispatched with the transcript, brand kit, and an optional
  dispatch-time frame-1 still, returning ranked **text-hook candidates** as a proposal.

The Director picks one candidate, places it as a `title` overlay in the reserved 0–3s hook window
(already protected by Phase 1's pacing reconciler), and keeps it distinct from the captions track.

## User Stories

1. As a creator, I want an on-screen text hook on the first 1–3 seconds, so that a muted scroller has
   a reason to stop.
2. As a creator, I want the text hook to say something different from but consistent with my spoken
   hook, so that the two channels cover more ground instead of repeating.
3. As a creator, I want the text hook to never be a false or over-promised claim, so that viewers are
   not baited and my reach is not throttled.
4. As a creator, I want the text hook styled to my brand kit's display font and colors, so that it
   matches the rest of the video.
5. As a creator, I want the text hook to sit clear of the top handle and the bottom UI band, so that
   no platform chrome covers it.
6. As the Director, I want to dispatch the TextHookAgent with the transcript, goal/audience, and brand
   kit, so that the worker can derive the payoff and propose hooks.
7. As the Director, I want to optionally attach a rendered frame-1 still to the dispatch, so that the
   worker can check the hook for collision with what is on screen and for thumbnail fit — without raw
   source-frame extraction.
8. As the Director, I want the worker to return ranked candidates with a recommended pick, so that I
   can place the best one or fall back to the brief's choice.
9. As the Director, I want to place the chosen hook with a single `add_title` op, so that authoring
   the hook stays one validated Builder op like everything else.
10. As the Director, I want the `title` overlay confined to the reserved 0–3s hook window, so that it
    does not compete with later overlays.
11. As the Director, I want the `title` overlay to be visually distinct from captions, so that it does
    not read as just another caption.
12. As the Director, I want to re-dispatch the TextHookAgent if the candidates are weak, so that I can
    get a better set within the dispatch budget.
13. As the Director, I want to skip the TextHookAgent for a video that does not want a text hook, so
    that I do not place an unwanted headline.
14. As the TextHookAgent worker, I want to read the transcript for the real payoff, so that my hook is
    the most compelling *true* framing of what the video delivers.
15. As the TextHookAgent worker, I want to generate candidates across at least three distinct patterns
    (reinforce / complement / curiosity-gap / audience-callout / contradiction), so that I am not
    returning five variants of one idea.
16. As the TextHookAgent worker, I want to validate every candidate against hard constraints (length,
    frame-one presence, distinct-from-captions, safe zones, casing, no false claims), so that I never
    return a failing candidate.
17. As the TextHookAgent worker, I want to return a proposal and never place anything myself, so that
    the Director stays the single authoring authority.
18. As the kernel, I want the `title` overlay validated by the same two-phase envelope + params path
    as other overlays, so that a malformed title is rejected like any other op.
19. As the kernel, I want the `title` overlay to compile to the existing IR `TextLayer`, so that the
    Remotion backend renders it without learning a new node kind (ADR 0002 intact).
20. As a maintainer, I want the `title` overlay registered like `zoom`/`pan`/`insert`, so that adding
    it is a registry entry plus params schema, not a core-schema change.
21. As a maintainer, I want snapshot coverage for a composition containing a `title` overlay, so that
    its IR compilation is pinned.
22. As a maintainer, I want the TextHookAgent tested with a fake `ModelClient`, so that its proposal
    shape and constraint validation are verified without a live model.

## Implementation Decisions

- **New `title` overlay type (additive).** Added to the composition model as a sibling of
  `zoom`/`pan`/`insert`, registered in the overlay registry with its own params schema (text,
  region/placement, style token reference) and validated by the existing two-phase envelope + params
  path. It is an **additive** overlay — painted on top, participates in the paint (z) stack — distinct
  from transform overlays.
- **New `add_title` Builder op.** Added to the Builder op set and the advertised tool list. One op
  places one title overlay. Args: text, start/end, region (upper-third/center), and a brand-kit style
  reference (display font / color tokens, never hardcoded).
- **Compile to the existing IR `TextLayer`.** `compile_ir` maps a `title` overlay to a `TextLayer`
  node; no new IR kind, no backend change. Captions already use `TextLayer`, so the renderer path is
  proven.
- **TextHookAgent worker.** Dispatched via `dispatch_text_hook` (reuses Phase 1's in-loop dispatch +
  dispatch budget). Input: `transcript` (required), `goal`/`audience`, `brand_kit`, and an optional
  frame-1 still the Director renders at dispatch time. Output: a proposal of ranked candidates, each
  with text, pattern, word count, rationale, placement intent, and a recommended pick. It places
  nothing.
- **Hook window.** The Director places the chosen title only inside the 0–3s hook window the Phase 1
  pacing reconciler already keeps clear of competing overlays.
- **No raw source-frame extraction.** Because dispatch is in-loop (Phase 1), the Director can have
  already authored the opening scene and render `render_still(0)` for the worker — this supersedes the
  doc's "video frames" input for v1.

## Testing Decisions

- **What makes a good test here:** assert external behavior. For the kernel, *given a composition with
  a `title` overlay → the expected validation result and the expected compiled IR*. For the worker,
  *given a scripted fake `ModelClient` → a proposal whose candidates pass the hard constraints and are
  ranked*. No assertions on internals.
- **Modules to test:**
  - **`title` overlay validation** — valid title accepted; malformed params rejected via the params
    schema; envelope fields validated.
  - **`title` → `TextLayer` compilation** — pure `compile_ir` mapping, pinned by a snapshot.
  - **TextHookAgent** — fake-client test: candidates span ≥3 patterns, all pass hard constraints, a
    recommended pick is returned; degrades gracefully (single `reinforce` candidate) when the
    transcript has no discernible payoff.
- **Prior art:** existing kernel validation tests and the IR snapshot tests
  (`tests/snapshots/*.json`) for the overlay + compilation; the fake-`ModelClient` agent tests
  (`test_gemini_describe`, the loop tests) for the worker.

## Out of Scope

- The **SFXAgent** and `dispatch_sfx` (Phase 3).
- Animated/kinetic title styling beyond a static headline — v1 title is static, frame-one, no slow
  fade-in.
- A/B serving of multiple hooks at render time — the Director places one; alternates live in notes.
- Raw source-video frame extraction for the worker (the dispatch-time still covers v1).

## Further Notes

- The `text_hook_agent_system_prompt` doc is the brainstorming basis for the worker's prompt; its
  pattern toolkit and hard constraints carry over, but it places nothing (the Director authors).
- Glossary terms `Text hook` and `Spoken hook` were added to `CONTEXT.md` during design; keep the
  worker's language aligned with them.
