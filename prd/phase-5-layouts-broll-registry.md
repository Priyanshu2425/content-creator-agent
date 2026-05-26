# Phase 5 — Layouts + b-roll + Registry

## Problem Statement

After Phase 4, Compositions are built programmatically through validated Builder operations, but the visual vocabulary is still effectively a single full-frame talking head. Two things the reference-video shape depends on are missing: arrangements other than full-frame (the split-screen hook), and the ability to cut to b-roll. Both are blocked on infrastructure that does not yet exist.

The deeper gap is the **plugin Registry**. ADR 0001 says new arrangements are added by registering a new Layout preset with no schema change, and that geometry is owned by the preset, not written per-scene. ADR 0002 says the Composition compiles to a neutral IR by calling each plugin's `to_ir`, and that backends interpret the IR's layer kinds rather than per-type code. Neither is realized yet: there is no registry to look a Layout up in, no `to_ir` seam for plugins, and no completeness check to catch the drift that the plan calls out as build-failing (an overlay type that does not compile to IR, or an IR kind a backend cannot handle). Until the registry exists, `compile_ir` cannot be driven generically — it would have to hard-code each arrangement, which is precisely the NxM coupling ADR 0002 rejects.

There is also no notion of a **Transition**. CONTEXT.md fixes that a cut is the default and is never written, and that the `transitions` array is sparse and keyed by the scene a transition follows (`afterScene: <id>`). None of this is modeled, so even a simple crossfade between a hook and the host cannot be expressed.

This phase makes the system multi-arrangement, multi-scene, and registry-driven — the structural foundation the reference-video shape (split-screen hook → host → b-roll cut) sits on, and the seam every later plugin phase (effects in Phase 6) plugs into.

## Solution

Build the plugin **Registry** and wire `compile_ir` to drive plugins through it, then deliver the first Layout plugins, full-frame b-roll Scenes, and Transitions on top of that machinery — all backend-agnostic per ADR 0002.

**Registry and completeness check.** Add a kernel registry that maps Layout names (and, in later phases, overlay types and caption styles) to their plugin contracts. The registry is the single place `compile_ir` consults to find a plugin's `to_ir`. Alongside it, a **completeness check** asserts the two invariants the plan names: every registered plugin compiles to IR, and the backend handles every IR layer kind the plugins can emit. This check is a contract test that fails the build on drift (ADR 0002).

**Layout plugins: `full` and `split-h`.** Each Layout is a backend-agnostic plugin (a `contract` declaring its named Region slots and a pure `to_ir` producing an IR fragment, per the repo structure's `plugins/layouts/<name>/`). Geometry is owned by the preset, not authored per-scene (ADR 0001, CONTEXT.md): `full` exposes a single `full` Region filling the frame; `split-h` exposes `top` and `bottom` Regions split 50/50 by default and adjustable via `ratio`. Adding a new arrangement (left/right, PiP) later is a new registry entry with no schema change.

**Full-frame b-roll Scenes.** Per the b-roll boundary in CONTEXT.md, full-frame b-roll is a `full` **Scene** whose `full` Region item is a Reference to the screenshot/clip Asset, entering and leaving on a **hard cut**. This is the reference-video style and needs no new entity — it is an ordinary `full` Scene filled with a b-roll Asset, which the Phase 4 Builder already knows how to create. This phase makes such a Scene compile correctly through the registry to IR `media` layers.

**Transitions: cut (default) and crossfade (first non-cut).** A cut is the default boundary and is never written; it is not an authorable entity (CONTEXT.md). The `transitions` array is **sparse** — it lists only non-cut boundaries — and each entry is keyed by the Scene it follows (`afterScene: <scene id>`), never by absolute time (ADR 0001). The first non-cut Transition is `crossfade`. Compiling a crossfade emits the appropriate IR (an opacity cross-blend between the outgoing and incoming Scenes' layers around the boundary), interpreted by the backend through the existing IR layer kinds, not via per-transition backend code (ADR 0002).

**`compile_ir` driven via the registry.** `compile_ir` walks the Composition, resolves each Scene's Layout through the registry, calls the Layout plugin's `to_ir` to place Region items as IR `media` (and, where relevant, `text`/`audio`) layers, applies sparse Transitions keyed by `afterScene`, and threads the continuous voiceover as the master clock. The output is the neutral IR (ADR 0002); the only backend-specific code remains in the Remotion project, which interprets the IR's layer kinds.

Everything in this phase stays backend-agnostic: plugins are `contract` + `to_ir` (pure data, no render deps), the registry and completeness check live in the kernel, and the Remotion backend gains nothing type-specific — it continues to interpret IR layer kinds.

## User Stories

1. As a kernel developer, I want a plugin registry that maps a Layout name to its plugin contract, so that `compile_ir` can resolve any Scene's Layout without hard-coding arrangements.

2. As a plugin author, I want to register a new Layout preset without changing the Composition schema, so that adding an arrangement is purely additive (ADR 0001).

3. As a platform maintainer, I want a completeness check that asserts every registered plugin compiles to IR, so that a plugin missing its `to_ir` fails the build rather than failing at render (ADR 0002).

4. As a platform maintainer, I want the completeness check to assert the backend handles every IR layer kind the plugins can emit, so that drift between plugins and the backend is caught as a build failure (ADR 0002).

5. As a creator/host, I want a `full` Layout that fills the frame with a single Region, so that the simplest talking-head Scene keeps working through the new registry path.

6. As a creator/host, I want a `split-h` Layout exposing `top` and `bottom` Regions, so that I can author the split-screen hook from the reference video.

7. As a creator/host, I want the `split-h` divider to default to 50/50, so that the common case needs no extra configuration.

8. As a creator/host, I want to adjust the `split-h` split via `ratio`, so that I can weight the hook toward one Region when the shot calls for it.

9. As a plugin author, I want each Layout's geometry owned by its preset rather than written per-scene, so that there are no free-form rects in the Composition and arrangements stay named and reusable (ADR 0001, CONTEXT.md).

10. As a plugin author, I want each Layout to be a backend-agnostic plugin of `contract` plus a pure `to_ir`, so that no render dependency leaks into the Layout and a backend swap does not rewrite it (ADR 0002).

11. As an authoring agent, I want a Layout to declare exactly which named Region slots it exposes, so that the Phase 4 region-validity check can reject filling a Region the Layout does not have.

12. As a creator/host, I want full-frame b-roll to be an ordinary `full` Scene filled with a b-roll Asset, so that cutting to a screenshot uses the same authoring path as cutting to any Scene (CONTEXT.md b-roll boundary).

13. As a creator/host, I want full-frame b-roll to enter and leave on a hard cut, so that the reference-video b-roll style works without authoring any Transition.

14. As a kernel developer, I want a b-roll `full` Scene to compile to IR `media` layers via the registry, so that screenshots and clips render through the same neutral IR path as the host (ADR 0002).

15. As a creator/host, I want a cut to be the default boundary between Scenes and never written, so that I only author the boundaries that differ from a cut (CONTEXT.md).

16. As a plugin author, I want the `transitions` array to be sparse, so that a Composition lists only its non-cut boundaries and the absence of an entry means a cut.

17. As a creator/host, I want a `crossfade` Transition as the first non-cut option, so that I can soften a chosen Scene boundary.

18. As a kernel developer, I want each Transition keyed by the Scene it follows (`afterScene: <id>`), so that boundaries are addressed by stable Scene id, never by absolute time or index (ADR 0001).

19. As a kernel developer, I want a crossfade to compile to IR expressible through the existing layer kinds (an opacity cross-blend around the boundary), so that the backend needs no per-transition code (ADR 0002).

20. As a kernel developer, I want `compile_ir` to resolve each Scene's Layout through the registry and call its `to_ir`, so that compilation is generic over arrangements rather than a switch statement (ADR 0001, ADR 0002).

21. As a kernel developer, I want `compile_ir` to apply sparse Transitions by matching each `afterScene` id to its Scene boundary, so that crossfades land at the right boundaries regardless of Scene ordering changes.

22. As a kernel developer, I want `compile_ir` to thread the continuous voiceover through scene cuts as the master clock, so that the audio plays straight through and defines duration (CONTEXT.md, ADR 0005).

23. As a platform maintainer, I want the only backend-specific code to remain in the Remotion project interpreting IR layer kinds, so that this phase adds no per-Layout or per-Transition backend code (ADR 0002).

24. As a plugin author, I want a backend swap to require only a new IR interpreter and no Layout/Transition rewrites, so that the swappable-backend promise of ADR 0002 holds after this phase.

25. As an authoring agent, I want the Resolver (from Phase 4) to report `split-h`'s `top`/`bottom` Region fills, so that the textual timeline reflects multi-Region Scenes.

26. As an authoring agent, I want a Reference to carry an in-point so one long recording can be jump-cut across several Scenes, so that I can reuse the host recording across multiple cuts (CONTEXT.md Reference).

27. As a kernel developer, I want adding a new caption style or, later, overlay type to be a registry entry plus a `to_ir`, so that the registry built here is the same seam every later plugin phase uses.

28. As a platform maintainer, I want the IR-compilation snapshot tests to grow to cover layouts and the b-roll cut, so that the expected IR for the reference-video structure is pinned.

29. As a creator/host, I want a `split-h` hook to cut to a `full` host Scene and then to a `full` b-roll Scene, so that the full reference-video structure is expressible end to end after this phase.

30. As a platform maintainer, I want the registry to be the single source of truth for which plugins exist, so that the completeness check and `compile_ir` agree on the plugin set by construction.

31. As a plugin author, I want `split-h`'s `ratio` validated as part of the Layout contract, so that an out-of-range split is caught at authoring time rather than producing a malformed frame.

32. As a kernel developer, I want a Transition that names an `afterScene` id with no matching Scene to be rejected, so that dangling Transitions cannot reach the backend.

## Implementation Decisions

This phase adds the kernel `registry` module and the completeness check, modifies `compile_ir` to be registry-driven, and adds the first Layout plugins under `plugins/layouts/` (each a `contract` plus a pure `to_ir`). It honors ADR 0001 (Layout registry; transitions key off Scene ids; sparse transitions array) and ADR 0002 (registry; plugin `to_ir → IR`; backend interprets IR layer kinds, not per-type code). It does not touch the Remotion backend's type-handling: the backend continues to interpret only the IR's layer kinds.

**Registry.** The registry maps a plugin key (a Layout name here; overlay types and caption styles join the same registry in later phases) to its contract and `to_ir`. It is the single lookup `compile_ir` uses, so the plugin set is defined in exactly one place. A registry entry exposes, for a Layout, the named Region slots it provides and the geometry those Regions occupy — geometry owned by the preset (ADR 0001), so the Composition never carries free-form rects.

```
register_layout(name, LayoutContract)
LayoutContract = { regions: [region_name], to_ir(scene, ctx) -> [IRLayer] }
```

**Completeness check.** A contract test (not a runtime branch) over the registry asserts: every registered plugin has a `to_ir` that produces IR, and every IR layer kind the registered plugins can emit is one the backend interprets. This fails the build on drift, per the plan's Registry testing line and ADR 0002.

**Layout plugins.**
- `full`: one Region named `full`, geometry = entire frame. Its `to_ir` places the Region's Reference as an IR `media` layer covering the Scene's span.
- `split-h`: Regions `top` and `bottom`, default split 50/50, adjustable by `ratio` (validated by the contract). Its `to_ir` places each Region's Reference as an IR `media` layer with the geometry the preset assigns from `ratio`.

Region-validity (Phase 4 Validator) checks fills against exactly the slots a Layout's contract declares, so the registry is also the source of truth the Validator consults.

**Full-frame b-roll.** No new entity: a `full` Scene whose `full` Region is a Reference to a b-roll Asset (image or video). It compiles through the `full` Layout's `to_ir` to IR `media` layers and enters/leaves on a hard cut (the default boundary). This is the reference-video b-roll form from CONTEXT.md; floating b-roll (an `insert` overlay) is explicitly Phase 6.

**Transitions.** A cut is the default and is never written — not an authorable entity. The `transitions` array is sparse and each entry is `{ kind, afterScene }`, keyed by the stable Scene id the boundary follows (the ids the Phase 4 Builder assigns), never by absolute time or index (ADR 0001). `crossfade` is the first non-cut kind.

```
Transition = { kind: "crossfade", afterScene: <scene id> }   # sparse; cut implied by absence
```

`compile_ir` matches each `afterScene` to its Scene boundary and emits a crossfade as an opacity cross-blend on the outgoing and incoming Scenes' IR layers around the boundary — expressible through existing IR layer kinds so the backend needs no per-transition code (ADR 0002). A Transition naming an `afterScene` with no matching Scene is rejected.

**`compile_ir` driven via the registry.** `compile_ir` walks Scenes in order; for each it resolves the Layout via the registry and calls `to_ir` to emit Region-item `media` layers (captions continue to compile to `text` layers as in Phase 3); it applies sparse Transitions by `afterScene` match; and it threads the continuous voiceover as the master clock and duration source (CONTEXT.md, ADR 0005). The product is the neutral IR; the Remotion project remains the only backend-specific code and interprets the IR's three layer kinds.

## Testing Decisions

A good test asserts external behavior — the shape of the emitted IR and the observable contract of the registry — not the internals of any plugin or of `compile_ir`. Per the Testing approach, two test layers grow in this phase: IR-compilation snapshot tests and the registry completeness contract test.

IR-compilation snapshot tests: extend the Composition → expected IR JSON snapshots to cover a `full` Scene (already present from earlier phases), a `split-h` Scene (assert two `media` layers with the preset geometry for the default 50/50 and for a custom `ratio`), a full-frame b-roll `full` Scene (assert a `media` layer for the b-roll Asset entering/leaving on a hard cut), and a crossfade Transition (assert the opacity cross-blend around the named boundary). Because Compositions are now built through the Phase 4 Builder, these fixtures should be authored through Builder operations, not hand-written JSON. Snapshots pin the IR shape so a later refactor that changes a plugin's internals but not its output stays green.

Registry completeness contract test: assert every registered Layout (and any registered plugin) compiles to IR, and that every IR layer kind the registry can produce is one the backend interprets. This test must *fail the build* on drift — e.g. registering a Layout whose `to_ir` emits a layer kind the backend does not handle. This is the drift guard ADR 0002 relies on.

Transition tests: assert the sparse array semantics — a boundary with no entry is a cut and produces no crossfade IR; an entry keyed by `afterScene` produces the crossfade at exactly that boundary; an entry naming a non-existent Scene id is rejected. Assert that reordering Scenes does not misplace a crossfade, since Transitions key off ids, not position.

Region/Layout tests: assert that `split-h` exposes exactly `top` and `bottom` and `full` exposes exactly `full`, and that the Phase 4 region-validity check (now consulting the registry) rejects filling a Region a Layout does not declare. Prior art: the Phase 4 Builder/Validator/Resolver tests are the layer below; the render-path integration test continues to assert a fixture Composition renders to an mp4 of roughly the voiceover length with a non-black sampled frame, now exercising a multi-Scene Composition with a b-roll cut.

## Out of Scope

- Overlay plugins `zoom`, `pan`, and `insert`, including floating b-roll as an `insert` overlay — Phase 6. Only full-frame b-roll (a `full` Scene) is in this phase.
- Spatial effect targets (`full`/`top`/`bottom` as overlay targets) and z-order among additive overlays — Phase 6. The registry is built so overlay types slot into it later, but no overlay type is registered here.
- Additional Layout presets beyond `full` and `split-h` (left/right, PiP) — additive later via a registry entry; not delivered now.
- Transition kinds beyond `cut` (default) and `crossfade` — wipes, dissolves, and the like are not in this phase.
- New caption styles — the captions track and its three Phase 3 styles are unchanged; caption styles join the registry conceptually but no new style is added here.
- Backend changes — the Remotion project gains no per-Layout or per-Transition code; crossfade is expressed through existing IR layer kinds. A second backend (ffmpeg) remains out of scope for v1.
- Stores, RenderService async jobs, the authoring agent, and the review sub-agent — Phases 7, 8, 8b.

## Further Notes

The registry is the load-bearing deliverable of this phase even though Layouts and Transitions are the visible features. Once the registry and its completeness check exist, every later plugin phase (effects in Phase 6, more layouts and styles later) is a registry entry plus a pure `to_ir` — never a change to `compile_ir`, the Composition schema, or a backend. That is the concrete cash-out of ADR 0001's "register, don't modify" and ADR 0002's "one IR interpreter per backend."

The two decisions most worth defending in review are both fixed by CONTEXT.md and the ADRs. First, full-frame b-roll deliberately reuses the `full` Scene rather than introducing a b-roll entity — the b-roll boundary in CONTEXT.md makes full-frame b-roll a Scene and floating b-roll an overlay, so this phase does the Scene half and defers the overlay half cleanly. Second, Transitions key off `afterScene` Scene ids and live in a sparse array with cut implied by absence — this is exactly the anti-coupling move in ADR 0001 (no positional or temporal addressing), and it pays off in the Transition test that reorders Scenes without misplacing a crossfade.

By the end of this phase the full reference-video *structure* is expressible — a `split-h` hook cutting to a `full` host Scene and then to a `full` b-roll Scene, with an optional crossfade at a chosen boundary — and it compiles to IR generically through the registry. What remains for the reference-video *look* (the slow zoom on the host, floating inserts) is Phase 6 effects, which plug into the registry seam built here.
