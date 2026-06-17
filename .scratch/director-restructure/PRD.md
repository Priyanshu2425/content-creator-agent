# PRD: Director restructure — Phase 1 (Orchestrator + brand kit + in-loop dispatch)

Status: ready-for-agent

> Scope note: this PRD covers **Phase 1 only** of a larger restructure that turns the authoring
> agent into a **Director** orchestrating three **Workers** (`TextHookAgent`, `BrollGeneratorAgent`,
> `SFXAgent`). Phases 2–6 are listed under *Out of Scope* as the agreed roadmap and will get their
> own PRDs.

## Problem Statement

Today the pipeline is a fixed, linear sequence of independent agents (IdealCuts → GenerateBroll →
describe → authoring → AudioDecider → render). The "authoring agent" only places assets others
produced; nothing owns the video's cross-cutting consistency (design language, pacing, the master
timeline). Style is a hardcoded `DEFAULT_STYLE_BRIEF` placeholder, b-roll generation is a rigid
upstream stage that always runs whether or not the video needs it, and there is no single agent that
can *decide* what specialist help a given video actually needs. The creator cannot supply a brand,
and the system cannot adapt its work to the brief.

## Solution

Rename the authoring agent to the **Director** and make it a true orchestrator that still authors the
**Composition** through validated Builder ops (ADR 0001 holds — the Director never emits a Composition
wholesale), but now also:

- owns a locked **brand kit** built from an optional **brand profile** input (or derived from the
  brief), and injects it to every worker as the single source of truth for design language;
- **dispatches workers in-loop** as tools that return **proposals**, deciding per-video which
  specialists to call rather than running every stage unconditionally;
- folds the former IdealCuts planning into its own **timeline skeleton**;
- reconciles **pacing** behaviorally — filling static gaps with punch-ins, protecting the hook
  window, de-duplicating near-collisions, and reasoning about safe zones and competing overlays off
  the existing Resolver timeline.

Phase 1 proves this mechanism end-to-end by converting the existing b-roll generator into the first
in-loop worker (`dispatch_broll`). The text-hook and SFX workers follow in later phases.

## User Stories

1. As a creator, I want to supply an optional brand profile, so that my video uses my colors, font,
   and caption style instead of a generic default.
2. As a creator, I want the system to derive a sensible brand kit from my brief when I give no brand
   profile, so that I am never forced to define a brand to get a styled video.
3. As a creator, I want the brand kit locked for the whole video, so that every scene, overlay, and
   caption is visually consistent.
4. As the Director, I want to receive an optional `brand_profile` and load-or-derive a brand kit, so
   that I hold one authoritative design language before any worker runs.
5. As the Director, I want to inject the brand kit to every worker as compact tokens, so that workers
   style their assets to it and cannot drift into their own look.
6. As the Director, I want to reject or relabel any worker asset that ignores the brand-kit tokens,
   so that non-conformant assets never reach the render.
7. As the Director, I want to build a timeline skeleton (hard-cut plan, caption cadence, reserved
   hook window, known change list) from the manifest, so that I have the cross-layer change record
   that pacing reconciliation needs.
8. As the Director, I want the former IdealCuts cut-planning folded into my own skeleton step, so
   that cut planning lives with the agent that owns cross-video consistency.
9. As the Director, I want to dispatch a worker mid-loop as a tool and receive its proposal as a tool
   result, so that I decide what to do rather than following a fixed pipeline order.
10. As the Director, I want a small separate dispatch budget per worker, so that a confused run cannot
    spawn workers in a loop and run away on cost.
11. As the Director, I want worker dispatches to *not* consume the Builder-op budget, so that calling
    a specialist does not starve my authoring turns.
12. As the Director, I want to skip a worker a video does not need (e.g. no b-roll moments → never
    call `dispatch_broll`), so that I do not pay for work with no payoff.
13. As the Director, I want to re-dispatch a worker when its proposal is weak, so that I can get a
    better proposal instead of being stuck with the first one.
14. As the Director, I want a worker's proposal threaded back into my perception, so that my next
    turns can author Builder ops that place the accepted parts of it.
15. As the Director, I want to turn an accepted b-roll shot list into `fill_region`/`add_overlay`
    ops, so that I remain the single compositing authority (ADR 0002's neutral IR is untouched).
16. As the Director, I want a pacing reconciler that reads the Resolver timeline and reports static
    gaps, so that I can insert `zoom` punch-ins to keep the video moving.
17. As the Director, I want the reconciler to report competing-overlay collisions, so that I never
    leave two competing overlays on screen at once.
18. As the Director, I want the reconciler to report safe-zone violations against the brand-kit safe
    zones, so that overlays and inserts stay clear of the top handle and bottom UI band.
19. As the Director, I want to keep the 0–3s hook window clear of competing overlays, so that the
    opening reads cleanly even before the text-hook worker exists.
20. As the Director, I want to de-duplicate two changes that fall within the minimum change interval,
    so that motion does not stack redundantly on a single moment.
21. As the Director, I want to emit a self-computed pacing report in my notes, so that the result is
    auditable even though the kernel does not yet enforce pacing.
22. As the BrollGeneratorAgent worker, I want to be dispatched by the Director with the brand kit,
    pacing budget, and timeline context, so that my shots respect what the rest of the video is doing.
23. As the BrollGeneratorAgent worker, I want to produce standalone asset clips with Nano Banana and
    Remotion stat-viz and return a shot-list proposal, so that the Director composites, not me.
24. As the BrollGeneratorAgent worker, I want to report the change timestamp each shot contributes,
    so that the Director can reconcile global pacing.
25. As a maintainer, I want the brand-kit token assembly to be a pure, unit-tested module, so that
    its behavior is verifiable without an LLM or a render.
26. As a maintainer, I want the pacing reconciler to be a pure function over the timeline, so that
    gap/collision/safe-zone detection is tested in isolation.
27. As a maintainer, I want the timeline-skeleton merge to be a pure module, so that change-list
    merging is tested without invoking the cut-planning LLM.
28. As a maintainer, I want the existing submit-render gate and GeminiReview bookend kept unchanged,
    so that the correctness and full-motion quality backstops still apply to the Director's output.
29. As a maintainer, I want `StyleBrief` to become a projection of the brand kit, so that the stat-viz
    renderer keeps working while the hardcoded default is removed.
30. As a developer, I want the rename from authoring agent to Director to preserve existing behavior
    where unchanged, so that the restructure is incremental and the existing tests still describe the
    loop.

## Implementation Decisions

- **Director keeps the kernel/Builder loop (extends ADR 0004; rejects the brainstorm doc's "emit
  master JSON" model).** The Director authors by calling exactly one validated Builder op per turn;
  the Composition stays derived state (ADR 0001). Worker dispatch is layered on top of, not in place
  of, this loop.
- **Workers are in-loop dispatch tools, not pre-loop stages.** The Director loop advertises
  `dispatch_broll` (Phase 1) alongside the Builder ops. A dispatch runs the worker agent and returns
  its **proposal** as a tool result, which is threaded into the Director's perception for subsequent
  authoring turns.
- **Two budgets.** Builder ops keep their existing operation budget. Worker dispatches draw from a
  separate, small per-worker dispatch budget (recommended ≤2 calls per worker) so dispatch cannot
  exhaust authoring turns and a runaway cannot re-dispatch indefinitely.
- **Workers return proposals; the Director alone authors and composites.** The b-roll worker produces
  standalone asset files (Nano Banana stills + Remotion stat-viz clips) and returns a shot-list
  proposal with placement/animation intent expressed in brand-kit tokens plus a contributed-change
  timestamp. The Director converts accepted shots into `fill_region`/`add_overlay` ops. No second
  agent composites into Remotion (ADR 0002 intact).
- **Brand profile → brand kit.** New optional `brand_profile` pipeline input. The **BrandKit builder**
  loads it if present, else derives a kit from the brief, then locks it. v1 brand-kit tokens:
  colors (bg/primary/accent), font, caption style (mapped to the fixed `pill`/`word-bold`/`kinetic`
  set), sfx palette + density budget (carried for Phase 3), frame meta (from `MediaManifest`), and
  **safe zones**. `StyleBrief` is re-expressed as a projection of the brand kit; `DEFAULT_STYLE_BRIEF`
  is removed as the source of truth.
- **IdealCuts folds into the Director's timeline skeleton.** The deterministic merge (hard cuts +
  caption cadence + reserved hook window → a single sorted change list) is a pure **Timeline skeleton**
  module; the LLM cut-planning becomes part of the Director's reasoning rather than a standalone
  upstream stage.
- **Pacing is Director behavior, not kernel enforcement.** A pure **Pacing reconciler** consumes the
  Resolver timeline + pacing budget + safe zones and returns a report of static gaps, competing-overlay
  collisions, and safe-zone violations. The Director acts on it with existing ops (`zoom` punch-ins to
  fill gaps; drop the weaker of near-duplicate changes). The kernel validator is unchanged in Phase 1;
  a kernel-enforced pacing pass is Phase 4.
- **Pacing budget shape:** `{ target_change_interval_seconds: [min,max], max_static_gap_seconds,
  min_change_interval_seconds, hook_window }`, tuned by the brief's goal (ad vs organic).
- **Bookends kept.** The describe stage (for user-supplied b-roll), the submit-render gate, and the
  GeminiReview finalization round are retained unchanged around the Director.
- **Punch-in = `zoom` overlay.** No new overlay type is needed in Phase 1; gap-fill punch-ins reuse
  the existing `zoom` overlay within the brand-kit motion range.

## Testing Decisions

- **What makes a good test here:** assert external behavior through a module's public interface, not
  its internals. For the pure modules, that means *given inputs → returned value*; for the loop, that
  means *given a scripted fake `ModelClient`, the Director produces the expected ops/dispatches and
  terminates correctly*. No assertions on private call order or intermediate state.
- **Modules to test (the four agreed):**
  - **BrandKit builder** — given a brief with no profile → a derived, locked kit; given a brand
    profile → it is loaded and locked; caption style maps to the fixed set; safe zones present.
  - **Pacing reconciler** — given a synthetic Resolver timeline + budget → correct gaps, collisions,
    and safe-zone violations; empty report when the timeline is within budget.
  - **Timeline skeleton merge** — given hard cuts + caption cadence + hook window → a single sorted,
    de-duplicated change list with the hook window reserved.
  - **Dispatch budget** — accounting unit: dispatches decrement the per-worker budget, are refused at
    zero, and do not touch the Builder-op budget.
- **Prior art:** follow the existing fake-`ModelClient` loop tests for the Director integration path,
  and the `test_stat_viz` / `test_creation` style for the pure modules (construct inputs, assert the
  returned value, inject fakes for any backend).

## Out of Scope

- **Phase 2 — TextHookAgent:** new additive `title` overlay type + `add_title` Builder op +
  compile_ir → `TextLayer` mapping + snapshots; the `TextHookAgent` worker + `dispatch_text_hook`
  (transcript + brand kit + optional dispatch-time frame-1 still).
- **Phase 3 — SFXAgent:** recast `AudioDeciderAgent` as the `dispatch_sfx` worker; Director-owned
  `event_timeline`; decouple the `whoosh` transition's built-in sound so the SFXAgent is the sole SFX
  authority; v1 = 3-sound palette (`click`/`whoosh`/`dramatic_whoosh`), cut-bound.
- **Phase 4 — Pacing validator:** kernel-enforced max-static-gap / collision / safe-zone checks, only
  if behavioral pacing proves insufficient.
- **Phase 5 — Retrieval toolset:** `fetch_logo` / `capture_screenshot` / `search_stock_footage` /
  `extract_article` + generate-vs-retrieve routing in the b-roll worker. (The Perplexity retrieval
  path was deliberately removed; this rebuilds retrieval cleanly later.)
- **Phase 6 — Audio/graphics polish:** music bed → ducking → loudnorm; graphics tokens (lower-thirds,
  brand bug) and motion tokens. Gated on music existing in the pipeline, which it does not today.
- **Free-timestamp SFX** (mid-scene `caption_emphasis`) — needs a new audio-overlay track; deferred.
- **The doc's 7-key SFX palette** (riser/pop/impact/tick/confirm) — those asset files do not exist.

## Further Notes

- Two decisions in this restructure are recorded as ADRs: **ADR 0008 — the Director dispatches
  workers in-loop while still authoring via Builder ops** (extends ADR 0004; governs this phase), and
  **ADR 0009 — the SFXAgent becomes the single SFX authority and the `whoosh` transition loses its
  built-in sound** (Phase 3; changes render behavior and snapshot tests).
- The four source documents (`director_agent_system_prompt`, `text_hook_agent_system_prompt`,
  `broll_generator_agent_system_prompt_v2`, `sfx_agent_system_prompt`) are brainstorming inputs, not
  literal specs — they describe an idealized greenfield system. Where they conflict with the kernel
  (e.g. "emit master JSON", "broll never calls Remotion", a 7-key palette), the resolved design in
  this PRD wins.
- Glossary terms added to `CONTEXT.md` during design: Director, Worker, Proposal, Brand kit, Brand
  profile, Text hook, Spoken hook.
