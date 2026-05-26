# PRD — Phase 6: Effects (zoom / pan / insert overlays)

## Problem Statement

By the end of Phase 5 the system can author and render the base layer: scenes with `full` and `split-h` layouts, full-frame b-roll scenes, transitions (cut and crossfade), and word-synced captions, all compiled through the registry into the neutral IR and rendered by the Remotion backend. What it cannot yet do is add motion and emphasis *on top of* that base layer. The reference-video shape calls for a host that slowly zooms in during a monologue, a pan across a wide region, and a floating screenshot card dropped over a continuing scene. None of these exist.

These three actions — `zoom`, `pan`, `insert` — are precisely the overlay types the glossary names as built-ins beyond captions. They are the first effect overlays in the system, and they are the first place where the transform-versus-additive distinction (CONTEXT.md, ADR 0001) becomes load-bearing rather than theoretical. Getting this distinction wrong corrupts every frame: if `zoom` were treated as a painted layer it would scale the captions sitting above it; if `insert` were treated as a transform it would silently reshape the host instead of appearing as a card. The phase exists to introduce effect overlays correctly, behind the same plugin contract every action follows, without touching the core envelope schema, the backends, or the runtime state model.

A second problem this phase solves is establishing how an effect names *what it acts on*. Effects must target spatial frame regions (`full` / `top` / `bottom`) resolved against the frame, never scene indices or assets, so that effects stay order-independent and seek-stable in the spirit of ADR 0001. Phase 6 is where that targeting model is first implemented and validated.

## Solution

Phase 6 ships three overlay plugins — `zoom`, `pan`, and `insert` — each as a self-contained plugin folder under `plugins/overlays/`, each consisting of a `contract.py` (the param schema, defaults, and the overlay type's metadata registered into the overlay registry) and an `ir.py` exposing a pure `to_ir(params, envelope_context) → IR fragment`. Per ADR 0002, the `to_ir` functions are the only effect-specific code; they emit IR keyframes and layer descriptions in the neutral IR vocabulary, and no backend gains any per-overlay-type knowledge. The Remotion backend continues to interpret only the three IR layer kinds (media / text / audio) plus the IR's transform, keyframe, opacity, and z primitives.

The plugins divide cleanly along the transform/additive axis fixed in the glossary and ADR 0001:

- `zoom` and `pan` are **transform overlays**. They reshape their target *base region* over time by emitting transform keyframes (scale and translate) that the IR applies to the existing base-layer content occupying that region. They are *not painted* — they emit no new painted layer, they do not participate in the z paint stack, and they never scale or move the layers (captions, inserts) sitting above the region.
- `insert` is an **additive overlay**. It paints a new media layer on top of the frame, positioned by `anchor` and `scale`, ordered against other painted things by `z`. It participates in the paint stack. This is the "floating b-roll" form named in CONTEXT.md's b-roll boundary section — a card over a continuing scene — as distinct from full-frame b-roll, which remains a `full` scene from Phase 5.

Effect overlays carry a spatial **target region** (`full` / `top` / `bottom`) in their envelope, resolved against the frame. The compile path resolves a transform overlay's target to the geometry of that frame region for the overlay's active span; `full` is always valid, while `top`/`bottom` are valid only while a scene exposing those regions (i.e. a `split-h` scene) is active. Validation of target validity over the overlay's span is reported through the existing two-tier validator from Phase 4.

The z paint order is implemented as the single explicit ordering space shared across overlays and captions. The compile path sorts only additive things (inserts and captions) into the paint stack by `z`. Transform overlays carry a `z` field structurally (they share the envelope), but it is inert: a transform overlay's `z` does not pull any painted layer into its transform.

## User Stories

1. As a creator/host, I want a slow zoom on my talking head during a monologue, so that a static full-frame shot gains motion and holds the viewer's attention.
2. As a creator/host, I want to pan across a region over time, so that I can guide the viewer's eye without re-shooting or re-cropping the source.
3. As a creator/host, I want to drop a floating screenshot card over a continuing scene, so that I can cite a tweet or show a reference without cutting away to a full-frame b-roll scene.
4. As a creator/host, I want my captions to stay crisp and unscaled while the host zooms underneath them, so that the text remains readable and correctly placed regardless of any transform on the base region.
5. As a creator/host, I want a zoom on the `top` region of a split-screen to leave the `bottom` region untouched, so that effects stay scoped to the part of the frame I intend.
6. As a creator/host, I want a floating insert to sit above the host but below the captions when I choose that ordering, so that the card never obscures the words on screen.
7. As a creator/host, I want effects to be editable and reorderable without surprises, so that adding or moving one effect does not silently shift another.
8. As an authoring agent, I want `zoom`, `pan`, and `insert` to be addable through the same `addOverlay` Builder op envelope I already use, so that I do not need effect-specific authoring code.
9. As an authoring agent, I want each effect overlay's type-specific params validated against `registry[type]` immediately on add, so that I learn about a bad `scale` or `anchor` value at the op that introduced it.
10. As an authoring agent, I want to target an effect at `full`, `top`, or `bottom` purely spatially, so that I never have to reason about scene indices or asset ids to place an effect.
11. As an authoring agent, I want a warning (or error per the validator's gating) when I target `top`/`bottom` during a span where no scene exposes that region, so that I catch effects aimed at a region that does not exist at that time.
12. As an authoring agent, I want the Resolver timeline to show which effect overlays are active at a given `t` and what region each targets, so that I can reason about my edit without rendering.
13. As an authoring agent, I want to set `z` on an insert relative to captions, so that I can control whether a card sits above or below the caption track.
14. As an authoring agent, I want to know that setting `z` on a `zoom` has no painting effect, so that I do not mistakenly expect a transform to participate in the paint stack.
15. As an authoring agent, I want an insert positioned by `anchor` and `scale`, so that I can place a card by intent (e.g. top-right, 30% width) rather than by raw pixel rectangles.
16. As an authoring agent, I want effects to compile to deterministic IR, so that the same Composition always yields the same render and my snapshot expectations hold.
17. As an authoring agent, I want a still frame at `t` mid-effect to reflect the effect's interpolated state, so that on-demand vision shows me the effect at that instant (consuming the same IR the video render does).
18. As a plugin author, I want to add a new effect by creating one plugin folder with `contract.py` + `ir.py`, so that a new action never touches the core envelope schema or any backend (ADR 0001, 0002).
19. As a plugin author, I want a clear template from the three built-in effect plugins showing the transform-emitting shape and the additive-painting shape, so that I can classify and implement my new effect correctly.
20. As a plugin author, I want `to_ir` to be a pure function with no render dependencies, so that my plugin's render facet can live in the shared kernel and stay backend-agnostic.
21. As a plugin author, I want the registry to reject my plugin at the completeness check if it declares an overlay type but fails to compile to IR, so that drift is caught at build time rather than at render time.
22. As a plugin author, I want my transform overlay to declare itself as transform (not additive), so that the compile path correctly keeps it out of the paint stack.
23. As a render-service developer, I want effects expressed entirely as IR transform keyframes, opacity, z, and painted layers, so that the backend interprets only the three layer kinds and the IR primitives, never per-effect logic.
24. As a render-service developer, I want a transform overlay's keyframes applied to the existing base-region content rather than to a new layer, so that no extra layer is composited for a zoom or pan.
25. As a render-service developer, I want the keyframe sampler in the Remotion project to interpolate effect keyframes with the declared easing, so that motion looks intentional and matches `render_still` sampling.
26. As a render-service developer, I want to add an FfmpegBackend later and interpret the same effect IR without rewriting any plugin, so that the swappable-backend guarantee of ADR 0002 holds for effects.
27. As a platform maintainer, I want the transform/additive distinction enforced structurally rather than by convention, so that a future effect cannot accidentally scale the layers above it.
28. As a platform maintainer, I want effect targeting restricted to spatial frame regions, so that effects never reintroduce the positional/temporal coupling ADR 0001 rejected.
29. As a platform maintainer, I want IR snapshot tests that grow to cover effects, so that a change to an effect's compiled output is reviewed deliberately.
30. As a platform maintainer, I want the registry completeness contract test to assert every overlay type — now including the three effects — compiles to IR, so that the build fails on any plugin/backend drift.
31. As a platform maintainer, I want effects to leave the runtime state model derived (scene at `t` + active overlays at `t`), so that adding effects does not reintroduce replay-based state.

## Implementation Decisions

**Modules built.** Three new plugin folders under `plugins/overlays/`: `zoom/`, `pan/`, and `insert/`, each containing `contract.py` and `ir.py`. No core schema changes: `zoom`, `pan`, and `insert` are registered as overlay types through the overlay registry (`registry.py` from Phase 5), mapping `type → {param schema, defaults, transform-or-additive classification, to_ir}`. This honors ADR 0001's central consequence: adding an action is registering a new overlay type; the core envelope schema is untouched.

**Modules modified.** `kernel/compile_ir.py` gains the logic to drive these overlay plugins' `to_ir` via the registry and to assemble the results correctly: transform overlays' emitted transform keyframes are bound to the geometry of their target base region (resolved per the active scene over the overlay span), additive overlays' emitted painted layers are inserted into the z-ordered paint stack alongside captions, and a transform overlay's emitted fragment is applied to existing base-region content without introducing a new painted layer. `kernel/resolver.py` is extended to report active effect overlays and their target region at `t` for the agent-facing timeline (ADR 0004). `kernel/validator.py` is extended with target-region validity checks over an overlay's span. The Remotion `project/` keyframe sampler is exercised by effect keyframes but gains no per-effect-type code (ADR 0002); if any IR transform primitive is missing it is added to the IR vocabulary uniformly, touching the IR and the one backend interpreter, not the plugins.

**The transform/additive contract.** Each effect plugin declares its kind. `zoom` and `pan` are transform overlays; `insert` is an additive overlay. This classification is part of the registry entry and drives compile-time routing in `compile_ir.py`. Per CONTEXT.md and ADR 0001: a transform overlay reshapes its target base region and is not painted — it never scales the layers above it and does not participate in the z paint stack; an additive overlay is painted on top and participates in the paint stack. Only additive things (inserts and captions) are sorted by `z`. A transform overlay structurally carries the shared envelope `z` field, but `compile_ir.py` treats it as inert for paint ordering.

**Targeting.** Effect overlays carry a spatial target region in the type-agnostic envelope — `full`, `top`, or `bottom` — resolved against the frame, never by scene index or asset (CONTEXT.md "Target (region)"; ADR 0001). `full` is always valid. `top` and `bottom` are valid only during spans where the active scene exposes those regions (a `split-h` scene). The compile path resolves the target to that frame region's geometry per active scene across the overlay's span; where the overlay span crosses a scene boundary, the target geometry is resolved per the scene covering each sub-span.

**IR emission shape (decision sketch, ADR 0002).** The plugins emit neutral IR, not Remotion. Illustrative shapes encoding the decisions:

- `zoom.to_ir` emits a transform fragment bound to the target region: a scale track and (optionally) a focal translate track as keyframes over `[start, end]` with easing, e.g.
  `{ kind: "transform", target_region: "full", scale: [{t: s, v: 1.0, ease: "easeInOut"}, {t: e, v: 1.2}], translate: [...] }`.
- `pan.to_ir` emits a translate track (and no net scale change) over the target region across `[start, end]`.
- `insert.to_ir` emits an additive painted `media` layer referencing the inserted asset, positioned by `anchor`/`scale`, with an `opacity` track if a fade is specified, and a `z` that places it in the paint stack, e.g.
  `{ kind: "media", ref: {asset, in?}, anchor: "top-right", scale: 0.3, z: 50, opacity: [...] }`.

These are illustrative of the *decisions* (transform fragments target a region and add no painted layer; inserts are painted media layers ordered by z), not a frozen literal schema. The backend interprets `kind: "transform"` against existing base-region content and `kind: "media"` as a composited layer — exactly the three layer kinds plus transform/opacity/z primitives, with no per-effect-type branch.

**z paint order.** A single explicit ordering space shared across overlays and captions (CONTEXT.md "z (paint order)"). `compile_ir.py` collects all additive things — inserts and captions — and orders them by `z`; convention keeps captions at high `z` so text stays on top. Transform overlays are excluded from this ordering entirely.

**Builder/authoring surface.** No new Builder op is required: effects are added via the existing `addOverlay` envelope (type + start + end + region/target + type-specific params), with per-op two-phase validation — the fixed core schema validates the envelope, `registry[type]` validates the params (CONTEXT.md "Envelope"). This keeps the imperative authoring API of ADR 0004 unchanged while extending the declarative vocabulary.

**Runtime state.** Unchanged and derived: on-screen state at `t` is the scene covering `t` plus the overlays active at `t`, including effects (ADR 0001). Effects introduce no mutable replayed state.

## Testing Decisions

A good test in this phase asserts external, observable behavior — the compiled IR and the rendered frame — not the internal structure of a plugin. Tests draw on three lanes of the plan's testing approach.

**IR compilation snapshot tests** are the primary lane. Following the plan's snapshot approach (Composition → expected IR JSON, growing per phase: host-only → captions → layouts → effects), we add fixture Compositions exercising each effect and assert the compiled IR matches expectation. The load-bearing assertions are behavioral distinctions, not field-by-field: a `zoom`/`pan` on a region emits a transform fragment bound to that region and adds *no* new painted layer and does *not* appear in the paint stack; an `insert` emits exactly one additional painted media layer ordered correctly by `z` against captions; captions and inserts share one z space and sort as expected; a `zoom`'s `z` does not reorder any painted layer. A snapshot showing a zoom under captions must demonstrate the captions' layer is unscaled by the transform.

**Validator tests** (TDD, continuing Phase 4's lane) assert target-region validity: a `top`/`bottom` target during a span with no scene exposing that region is reported (warning or error per the validator's gating), while a `full` target is always valid; an effect spanning a scene boundary resolves its target per the covering scene. Tests assert reported outcomes, not validator internals.

**Registry completeness contract test** (continuing Phase 5's lane) is extended so every overlay type — now including `zoom`, `pan`, `insert` — compiles to IR and the backend handles every emitted IR kind. This test fails the build on drift, which is its whole purpose.

**Resolver tests** assert the textual timeline reports active effect overlays and their target regions at sampled `t`, since this is the agent's eyes (ADR 0004) and a behavioral surface.

**Render-path integration test** (per the plan's per-phase fixture → mp4 lane) renders a fixture Composition with at least one zoom and one insert: assert the file exists, duration ≈ host length, and a sampled frame mid-effect is non-black. A complementary `render_still(t)` assertion mid-zoom confirms the still and the video sample the same interpolated effect state.

Prior art to mirror: the Phase 3 caption IR snapshots (kinetic = opacity/scale keyframes) are the closest existing pattern for keyframe-emitting plugins, and the Phase 5 layout/registry tests are the model for the completeness contract test.

## Out of Scope

- Any per-backend effect implementation. There is one IR; the only render code remains in `backends/remotion/`. No `zoom.remotion`/`zoom.ffmpeg` split (rejected in ADR 0002).
- Effect types beyond `zoom`, `pan`, `insert`. New effects are a later plugin-folder change, not part of this phase.
- Alpha masks and clip-level masking beyond what the IR already carries (per the plan's v1 out-of-scope list).
- Stores, persistence, undo/redo, the async RenderService job API (those are Phase 7).
- The authoring Agent and Builder-ops-as-Claude-tools wiring (Phase 8); this phase only ensures effects are addable through the existing `addOverlay` envelope.
- Free-form geometry / per-scene rects for effects; targeting is restricted to the named spatial frame regions.
- Extending the IR transform vocabulary beyond what zoom/pan/insert require; any such extension is done uniformly across IR + backend only if a built-in effect needs it.

## Further Notes

- The crucial correctness invariant, restated for implementers: a transform overlay (`zoom`/`pan`) reshapes its target base region and emits no painted layer, so it cannot scale captions or inserts above it; an additive overlay (`insert`) is the only effect that joins the paint stack. Treating these symmetrically is the most likely bug and the thing snapshot tests must guard.
- The transform/additive classification belongs in each plugin's `contract.py` and the registry entry, not inferred by `compile_ir.py` from the type name — keep the classification declared so a new plugin author states it explicitly.
- Floating b-roll (an `insert` overlay) and full-frame b-roll (a `full` scene from Phase 5) are both first-class per CONTEXT.md; this phase delivers the floating form. The author picks per shot.
- Easing on effect keyframes should reuse the IR's existing easing vocabulary established for kinetic captions in Phase 3, so the keyframe sampler stays uniform across captions and effects.
- This phase is the last purely-kernel/render phase before persistence and the async job API arrive in Phase 7; keeping `to_ir` pure here keeps the kernel render-dependency-free for the AuthoringService in Phase 8.
