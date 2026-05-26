# Phase 1 — Contract Types

## Problem Statement

The entire system is organized around one idea: the **Composition** JSON is the message contract between the three services, and rendering goes through a neutral **IR** so backends are swappable. But after Phase 0 there is no actual type for a Composition and no actual type for the IR — only empty placeholder modules. Every later phase depends on these types existing and being correct:

- The Builder (Phase 4) constructs a Composition by accumulating operations; it needs Composition types to build into.
- `compile_ir` (Phase 5) turns a Composition into IR by driving plugins' `to_ir`; it needs both the Composition types it reads and the IR types it emits.
- The RenderService and backends (Phases 2, 7) consume the IR; they need a stable IR vocabulary.
- The CompositionStore (Phase 7) serializes and deserializes the Composition; it needs the document to round-trip through JSON losslessly.
- The authoring agent (Phase 8) perceives and edits the Composition; it needs a validated, well-shaped document.

A backend engineer or kernel developer trying to start any of that today has no shared vocabulary expressed as code. Worse, the risk is not just absence but incorrectness: if the Composition types do not faithfully encode the declarative scene-plus-overlay model (ADR 0001), the neutral-IR boundary (ADR 0002), and the JSON-as-contract requirement (ADR 0003), then every consumer inherits the mistake. Hand-written test compositions would drift from whatever the code actually accepts, and "the Composition JSON is the contract" would be aspirational rather than real.

## Solution

Implement the two contract modules in the shared kernel as Pydantic v2 models: `kernel/composition.py` (the authored, declarative document) and `kernel/ir.py` (the neutral render intermediate representation). These are pure data types with validation — no Builder, no compiler, no render logic.

`composition.py` models the Composition and everything it holds, using the glossary terms exactly: a top-level Composition with a schema `version` and strict-mode flag, an Asset library (`id → {type, src}`), the **Voiceover** (the master-clock audio), an ordered list of **Scenes** (each picking a **Layout** and filling its **Regions** via **References** that may carry an in-point), the sparse **Transitions** array keyed by `afterScene`, the **Overlay** union (transform overlays like `zoom`/`pan` and additive overlays like `insert`, sharing a common **Envelope**), and the dedicated **Captions** track (each carrying `text`, `start`/`end`, and a **caption style**).

`ir.py` models the backend-agnostic render IR: a flat, timed list of **Layers** of three kinds — `media`, `text`, `audio` — with common fields (timing, `z` paint order, opacity, transform, target/region as applicable) and an animation vocabulary of **Value** tracks built from **Keyframes** with **easing**. This is the vocabulary that ADR 0002 says every backend interprets — backends read the three layer kinds, not per-overlay-type code.

Both modules round-trip through JSON (serialize then deserialize back to an equal model) and validate their inputs, proven by unit tests. After this phase, every later module has real, validated types to build on, and the Composition-as-contract and neutral-IR decisions are encoded in code rather than only in prose.

## User Stories

1. As a kernel developer, I want a top-level `Composition` Pydantic v2 model, so that the whole video document has one well-typed root that all three services import (per ADR 0003).
2. As a kernel developer, I want the Composition to carry a schema `version` field, so that documents are versioned and a newer document can degrade on an older renderer (per the glossary's Version / strict mode).
3. As a kernel developer, I want a `strict` flag on the Composition (defaulting to strict-on), so that an unknown overlay `type` is an error by default but can be downgraded to skip-with-warning, matching ADR 0001 and the glossary.
4. As a kernel developer, I want an `Asset` model (`id`, `type` ∈ {`video`, `image`, `audio`}, `src`), so that media sources are declared once in the top-level library and referenced by id everywhere (per the glossary's Asset).
5. As a kernel developer, I want the Asset library modeled as an id-keyed collection, so that References resolve against it and the "declared once, referenced by id" rule is structural.
6. As a creator/host, I want the host recording's audio represented as the `Voiceover` (the master clock), so that it plays straight through scene cuts and defines the composition's duration (per ADR 0005 and the glossary).
7. As a kernel developer, I want an `Audio` model for the voiceover, so that the continuous primary audio is a typed entity (a reference to an audio Asset) rather than an untyped string.
8. As a creator/host, I want a `Scene` model that owns the base layer for a contiguous time span, carries a stable `id`, picks one `Layout`, and fills each Region with one item, so that the main visual cuts are first-class authoring units (per ADR 0001 and the glossary's Scene).
9. As a kernel developer, I want each Scene to carry `start`/`end` in absolute seconds, so that the single-axis Timeline measured in seconds is enforced (per the glossary's Timeline).
10. As a kernel developer, I want a Scene to name its Layout from the built-in layout registry (e.g. `full`, `split-h`) rather than free-form geometry, so that geometry stays owned by the preset and new arrangements are added without schema change (per the glossary's Layout).
11. As a kernel developer, I want a Scene's Region fills modeled as a mapping from named Region slot to a Reference, so that the "a scene fills each region with one item" rule is typed (per the glossary's Region).
12. As a kernel developer, I want a `Ref` (Reference) model pointing at an Asset by id, optionally carrying an in-point (`in`), so that one long recording can be jump-cut across many scenes and on-screen duration comes from the holding span, not the asset (per the glossary's Reference).
13. As a kernel developer, I want a `Transition` model with a sparse `transitions` array keyed by `afterScene: <id>`, so that only non-cut boundaries (e.g. `crossfade`) are listed and cut is never an authored entity (per the glossary's Transition and ADR 0001).
14. As a kernel developer, I want transitions keyed by stable scene id rather than absolute time, so that they avoid the temporal coupling that would reintroduce replay-style fragility (per ADR 0001).
15. As a kernel developer, I want an `Overlay` model with a shared `Envelope` (the type-agnostic fields: `type`, `start`, `end`, `region`/target, `z`), so that the fixed core schema validates every overlay regardless of type (per the glossary's Envelope, two-phase validation).
16. As a kernel developer, I want the Overlay `type` to be a discriminator (`zoom`, `pan`, `insert`, …), so that overlays form a registry-extensible union and adding an action means registering a new type, not changing the core schema (per ADR 0001 and the glossary's Overlay type).
17. As a kernel developer, I want the distinction between transform overlays (`zoom`, `pan`) and additive overlays (`insert`) represented in the types, so that only additive things participate in the paint stack and a transform never scales the layers above it (per the glossary's transform vs additive overlay).
18. As a kernel developer, I want overlays to carry a spatial `target`/`region` (`full`/`top`/`bottom`), so that effects name what they act on by frame region, never by scene index or asset (per the glossary's Target and ADR 0001).
19. As a kernel developer, I want a `z` (paint order) field shared across overlays and captions, so that painted (additive) things have one explicit ordering space and captions can sit on top by convention (per the glossary's z).
20. As a creator/host, I want a `Caption` model carrying `text`, `start`/`end`, and a caption style, kept on a dedicated `captions` track rather than in the overlays list, so that the voluminous, homogeneous captions stay separate (per the glossary's Caption).
21. As a kernel developer, I want a caption style enumeration of the three known presets (`pill`, `word-bold`, `kinetic`), so that a caption's appearance is a named preset, not an ad-hoc font spec (per the glossary's caption style).
22. As a kernel developer, I want all times (scenes, overlays, captions) expressed in absolute seconds from zero, so that seconds stay canonical and transcript word-timings compile down to this axis (per the glossary's Timeline).
23. As a backend engineer, I want a neutral `IR` root model, so that RenderService compiles a Composition into a backend-agnostic structure rather than rendering the Composition directly (per ADR 0002).
24. As a kernel developer, I want the IR to be a flat, timed list of `Layer`s, so that the declarative document is flattened into the primitive form every backend can interpret (per ADR 0002).
25. As a backend engineer, I want exactly three IR layer kinds — `media`, `text`, `audio` — so that a backend interprets the three layer kinds rather than per-overlay-type code, and adding an overlay never touches a backend (per ADR 0002 and the plan's reconciliation note).
26. As a backend engineer, I want each IR Layer to carry common fields (timing in seconds, `z` paint order, opacity, transform), so that backends have a uniform surface to render regardless of layer kind (per ADR 0002).
27. As a backend engineer, I want the IR `media` layer to reference a resolved media path/source and support an in-point, so that the backend can play the correct slice of an asset.
28. As a backend engineer, I want the IR `text` layer to carry text runs and a style, so that captions and kinetic text compile to text layers the backend can paint (per the plan's Phase 3 note that captions → IR `text` layers).
29. As a backend engineer, I want the IR `audio` layer to represent the voiceover (and any audio), so that the backend can mux audio against the visual layers (per the plan's Phase 2 note on media + audio mux).
30. As a kernel developer, I want a `Value` track and `Keyframe` model in the IR, so that animated properties (zoom/pan transforms, kinetic caption opacity/scale) are expressed as keyframed values the backend samples (per ADR 0002 and the plan's IR animation notes).
31. As a kernel developer, I want each Keyframe to carry a time (seconds), a value, and an easing, so that the backend's keyframe sampler can interpolate between keyframes (per the plan's "keyframe sampler" and IR animation).
32. As a kernel developer, I want an easing enumeration in the IR, so that interpolation between keyframes is a named, validated choice rather than free-form.
33. As a backend engineer, I want a transform on IR layers expressed via keyframed Value tracks (e.g. scale/translate), so that zoom and pan compile to transform keyframes the backend interprets uniformly (per ADR 0002 and IR animation).
34. As a platform maintainer, I want both the Composition and the IR to serialize to JSON and deserialize back to an equal model (round-trip), so that the Composition-as-contract (ADR 0003) is real and the CompositionStore can persist documents losslessly later.
35. As a backend engineer, I want the IR to serialize to JSON so it can be passed to the Remotion subprocess as `--props`, so that the Python ↔ Remotion seam (ADR 0002) consumes a stable serialized form.
36. As a kernel developer, I want each model to validate its inputs (reject malformed documents with clear errors), so that consumers fail fast on bad data rather than producing broken renders.
37. As a kernel developer, I want the Composition and IR types to live in the shared kernel with zero render or service dependencies, so that AuthoringService stays free of render deps and plugins' render facets stay pure data (per ADR 0002 and 0004).
38. As an authoring-agent integrator, I want the Composition types to be the exact structure the Builder will construct and the Resolver will read, so that later phases build on a contract that does not shift under them.
39. As a kernel developer, I want field names and discriminator values to match the glossary terms exactly, so that the code, the docs, and the agent's vocabulary stay in lockstep.
40. As a platform maintainer, I want the coverage rules encoded where they belong as types (scenes carry spans; gaps are representable; overlapping is detectable later by the validator), so that Phase 4's validator has the right shapes to check overlap-as-error and gap-as-warning.

## Implementation Decisions

- **Two modules, pure types.** `kernel/composition.py` holds the authored declarative document; `kernel/ir.py` holds the neutral render IR. Both are Pydantic v2 models. Neither contains Builder, compiler, validator, or render logic — this phase delivers only the type contracts and their built-in field validation. The split mirrors ADR 0002's separation of the authored document from the thing backends interpret.
- **Composition encodes the declarative model (ADR 0001).** The Composition is the two-layer model from the glossary: an ordered list of Scenes (the base layer, persistent layout state) plus an Overlay union and a Captions track (the declarative timed layers on top). There is deliberately no imperative action stream and no mutable runtime state in these types — state is meant to be derived from (scene covering `t`, overlays active at `t`), which these types make possible by carrying explicit spans.
- **Composition JSON is the contract (ADR 0003).** The Composition root carries a top-level `version` and a `strict` flag. The types are designed so the whole document serializes to and deserializes from JSON without loss; this is the message contract between the three services.
- **Asset library and References (glossary).** Assets are declared once in a top-level id-keyed library with `type` ∈ {`video`, `image`, `audio`} and a `src`. A Reference points at an Asset by id and may carry an in-point (`in`); the on-screen duration is determined by the holding span (the Scene), not stored on the Reference. The Voiceover is modeled as the master-clock audio (a reference to an audio Asset), consistent with ADR 0005 (host audio is the voiceover).
- **Scenes, Layouts, Regions (glossary, ADR 0001).** A Scene carries a stable `id`, a `start`/`end` span in absolute seconds, a named Layout drawn from the layout registry (validated against a fixed enumeration of known layout names for now — `full`, `split-h` — with extension handled by the registry in Phase 5), and a mapping from named Region slot to a Reference. No free-form rectangles: geometry belongs to the layout preset, not the Scene.
- **Transitions are sparse and id-keyed (glossary, ADR 0001).** The `transitions` array lists only non-cut boundaries, each keyed by `afterScene: <id>`. Cut is the default and is never authored, so it is not an entity in the types. Keying by scene id (not absolute time) is a deliberate choice to avoid temporal coupling.
- **Overlay union with a shared Envelope (glossary, ADR 0001).** Every overlay shares the Envelope fields (`type` discriminator, `start`/`end`, `target`/`region`, `z`). The `type` is a discriminator (`zoom`, `pan`, `insert`, …) selecting a member of a Pydantic discriminated union. The core Envelope schema is fixed; type-specific params are validated separately (the two-phase validation the glossary describes — full registry-driven param validation arrives with the registry in Phase 5, but the Envelope split is established here). Transform overlays (`zoom`, `pan`) and additive overlays (`insert`) are distinguished so that downstream paint/transform logic can treat them differently; only additive overlays and captions participate in the `z` paint stack.
- **Captions on a dedicated track (glossary).** Captions are not overlays; they live on the `captions` track. A Caption carries `text`, a `start`/`end` span in seconds, a caption style (`pill` / `word-bold` / `kinetic`), and participates in the shared `z` paint ordering.
- **IR is a flat list of three layer kinds (ADR 0002).** The IR root is a backend-agnostic structure whose body is a flat, timed list of Layers. There are exactly three layer kinds — `media`, `text`, `audio` — discriminated so a backend interprets the three kinds, never per-overlay-type code. This is the reconciliation the plan calls out: backends interpret the IR's three layer kinds, not overlay types.
- **Common layer fields and the animation vocabulary (ADR 0002, IR animation).** Every IR Layer carries common fields: a timing span in seconds, a `z` paint order, opacity, and (where applicable) a transform and a spatial target/region. Animation is expressed through a `Value` track composed of `Keyframe`s; each Keyframe carries a time in seconds, a value, and an `easing` drawn from an easing enumeration. Transforms (for compiled zoom/pan) and kinetic caption properties (opacity/scale) are represented as keyframed Value tracks so the backend's keyframe sampler can interpolate them uniformly.

  A trimmed shape sketch of the decision-bearing IR (illustrative, not the full module):

  ```python
  class Easing(str, Enum):
      linear = "linear"
      ease_in = "ease_in"
      ease_out = "ease_out"
      ease_in_out = "ease_in_out"

  class Keyframe(BaseModel):
      t: float            # absolute seconds
      value: float
      easing: Easing = Easing.linear

  class Value(BaseModel):          # a possibly-animated scalar
      keyframes: list[Keyframe]    # >= 1; a single keyframe == constant

  class LayerKind(str, Enum):
      media = "media"
      text = "text"
      audio = "audio"

  class Layer(BaseModel):
      kind: LayerKind              # discriminator: the 3 kinds backends interpret
      start: float                 # seconds
      end: float
      z: int                       # paint order (additive layers)
      opacity: Value
      # kind-specific fields (media src + in-point, text runs + style,
      # audio src) and an optional keyframed transform follow per kind
  ```

- **Glossary vocabulary is binding.** Field names and discriminator values follow the glossary exactly (Composition, Scene, Overlay, Voiceover, Timeline, Layout, Region, Asset, Reference, Caption, caption style, overlay type, Envelope, transform vs additive overlay, z, target, Transition, IR, Layer, Value, Keyframe, easing). This keeps the code, the docs, and the eventual agent vocabulary aligned.
- **Kernel purity (ADR 0002, 0004).** Both modules import only Pydantic and the standard library — no `backends`, no `services`. This is what lets the shared kernel be imported by all three services and lets plugins' `to_ir` facets later sit in the kernel with zero render dependencies.

## Testing Decisions

- A good test here checks external behavior of the types — what they accept, what they reject, and that they survive a JSON round-trip — not the private structure of any model. The two observable contracts are *round-trip fidelity* and *validation*.
- **Round-trip tests.** For both the Composition and the IR, serialize a representative model instance to JSON and deserialize it back, asserting the result equals the original. This proves the Composition-as-contract (ADR 0003) is real and that the IR can be safely passed to the Remotion subprocess as `--props` JSON (ADR 0002). Representative instances should exercise the interesting shapes: multiple Scenes with different Layouts, References with and without an in-point, a sparse Transitions array keyed by `afterScene`, both a transform overlay and an additive overlay in the union, several Captions across the three styles, and an IR with all three layer kinds plus a keyframed Value track using more than one easing.
- **Validation tests.** Assert that well-formed documents validate and that malformed ones are rejected with a clear error: an Asset with an unknown `type`, an unknown overlay `type` under strict mode, a caption with an unrecognized style, a missing required Envelope field, a Reference to a missing/invalid shape, negative or non-numeric times. These are the externally meaningful guarantees consumers depend on. (Cross-cutting semantic checks — scene overlap as error, gaps as warning, region-validity, caption alignment — are the Phase 4 validator's job and are explicitly not tested here; this phase only verifies per-model field validation.)
- **Modules under test.** `kernel/composition.py` and `kernel/ir.py`. Tests are unit tests with no external dependencies (no ffprobe, no Remotion, no network) — fast and deterministic.
- **Prior art / similar test types.** These round-trip and validation tests are the seed of the test families the plan's "Testing approach" describes: the IR snapshot tests (Composition → expected IR JSON) that grow per phase build directly on the IR types proven here, and the kernel TDD suites (Builder, validator, Resolver) from Phase 4 construct the Composition types proven here. Establishing trustworthy round-trip and validation behavior now is what makes those later snapshot and unit tests meaningful.

## Out of Scope

- The Builder ops (`addScene`, `fillRegion`, `addOverlay`, `addCaption`, `add_captions_from_transcript`) and any programmatic construction of a Composition — Phase 4.
- The two-tier Validator (local hard errors / global reported-and-gated): scene-overlap-as-error, gap-as-warning, region-validity, caption alignment, and the `submit_render` gate — Phase 4. This phase only does per-model field validation.
- The Resolver (`(composition, t) → frame description`) — Phase 4.
- The plugin Registry and its completeness check, and registry-driven type-specific overlay param validation — Phase 5.
- `compile_ir` (Composition → IR driving plugins' `to_ir`) — Phases 2 (minimal, media kind) and 5 (full, registry-driven).
- Layout and overlay plugin implementations (`full`, `split-h`, `zoom`, `pan`, `insert`) and caption-style rendering — Phases 5–6.
- The `RenderBackend` protocol, the Remotion subprocess wrapper, the Node IR-to-components, and the keyframe sampler implementation — Phases 2 and beyond. (This phase defines the IR they consume, not the consumers.)
- MediaService behavior, transcription, and resolving asset ids to filesystem paths — Phases 2–3.
- The CompositionStore (snapshot undo/redo, append-only journal) and blobs writer — Phase 7.
- The authoring agent, tools, in-loop vision, and review sub-agent — Phases 8–8b.
- All v1 out-of-scope items: S3 storage, script→TTS / no-footage path, distributed queue/RPC, alpha masks (clip-only), structured brief schema (free-text brief), human editor UI, and MediaService enrichments (silence/shot/salience).

## Further Notes

- This is the keystone phase for ADRs 0001, 0002, and 0003: the declarative model, the neutral IR, and the Composition-JSON-as-contract are all encoded as code here for the first time. Getting the shapes and the vocabulary right now pays off in every subsequent phase; getting them wrong propagates everywhere.
- The Composition is the *authored* document; the IR is what it *compiles into* for rendering. Keeping them as two distinct modules (not one shared shape) is deliberate — it is the boundary that makes backends swappable (ADR 0002). They should be tested independently as well as together via the eventual `compile_ir` snapshot tests in later phases.
- Where the registry will later own the full set of layout names and overlay types, this phase uses fixed enumerations of the known built-ins (`full`/`split-h`; `zoom`/`pan`/`insert`; `pill`/`word-bold`/`kinetic`). When the Registry arrives in Phase 5, the extension mechanism replaces the fixed enumeration without changing the Envelope/core schema — exactly the "adding a type does not touch the core schema" promise of ADR 0001. The types here should be written so that swap is additive.
- The strict-mode semantics (unknown overlay `type` errors by default; `strict: false` downgrades to skip-with-warning) are represented as a flag on the Composition now; the actual skip-with-warning behavior is exercised by the validator and compiler in later phases. This phase only ensures the flag and the version are present and serialize correctly.
- The animation vocabulary (Value/Keyframe/easing) is sized to the known effect surface (zoom, pan, insert, captions, kinetic text) per ADR 0002's consequence that effects are limited to what the IR can express. If a future effect exceeds this vocabulary, extending the IR is the deliberate, all-backends-touching change ADR 0002 anticipates — not something to pre-build here.
