# PRD: Caption library — caption renderer registry

Status: ready-for-agent

> Scope note: introduces the **caption style registry** (the "caption library") and amends ADR 0002
> for captions only — see `docs/adr/0010-caption-renderer-registry.md`. Glossary terms used here
> (caption renderer, caption style, caption style registry, caption gallery, base caption, feature
> caption) are defined in `CONTEXT.md`.

## Problem Statement

Captions today come in exactly three looks — `pill`, `word-bold`, `kinetic` — and the design ceiling
is hard: a **caption style** is a closed enum that the compiler bakes into flat visual props
(`TextStyle`: font/color/background/radius/padding/highlight + opacity/scale tracks), and the
Remotion backend paints purely from those props, never branching on a style name (ADR 0002). That
flat vocabulary provably cannot express the caption visuals we want. The seed we want to ship —
neon highlighter boxes where words split into separate wrapping boxes, each with rotation jitter and
a per-word spring pop — is irreducibly component-shaped, not a set of prop values. There is no way to
add a genuinely new caption visual without expanding the flat vocabulary, and no way for a future
frontend (or the creative-direction agent) to browse and pick a look. "Add a caption visual later"
is currently impossible.

## Solution

A **caption library**: an extensible registry of caption visuals. A **caption style** stops being a
closed enum and becomes a registered entry `{id, description, param schema, defaults, renderer}`. A
`text` layer in the IR carries its style `id` + typed params + word `runs`; the Remotion backend
looks the `id` up in a **caption renderer registry** and dispatches the layer to the matching React
component (a **caption renderer**). The same renderer components also back a **caption gallery** —
standalone Remotion compositions that preview each visual for a future frontend picker. Adding a new
caption visual becomes: drop a renderer component, register it on both the Python and TS sides, add a
gallery composition — no change to the core IR schema or any other layer kind.

The existing three styles migrate into this one uniform model (they become configs of a single
generic karaoke renderer); the highlighter look ships as the first net-new renderer, `highlight-box`.
**Base captions** (the auto-populated transcript track) take the brand kit's default caption style;
**feature captions** are the same entity with a style the creative-direction agent deliberately
chose, discovered by reading the registry's id + description.

## User Stories

1. As a video creator, I want captions that can look like neon highlighter boxes with per-word pops, so that my shorts match the styles I see performing on TikTok.
2. As a video creator, I want the three existing caption looks (`pill`, `word-bold`, `kinetic`) to keep working unchanged, so that nothing I already rely on regresses.
3. As a developer, I want to add a brand-new caption visual by writing one component and registering it, so that extending the library never means editing a core schema or every backend.
4. As a developer, I want the caption library to follow the same shape as the existing overlay registry, so that there is one mental model for "registered, name-keyed, param-validated renderers."
5. As a developer, I want each caption renderer to receive a stable contract — the caption's words with spoken windows, the layer window, canvas + fps, and its own typed params — so that I can build a visual without reaching into global state or the brand kit.
6. As a developer, I want a caption renderer to own its own phrase/box grouping and animation, so that the IR stays free of style-specific structure.
7. As a developer, I want the caption style registry to validate params against a per-style schema with defaults, so that a malformed or partial style spec fails loudly (or fills sensible defaults) at compile time.
8. As a developer, I want an unknown caption style id to be an error by default and a skip-with-warning under `strict: false`, so that captions degrade exactly like an unknown overlay type.
9. As a developer, I want the Python registry and the TS registry to be the two synchronized halves of one library, so that an id present on one side but missing on the other is a detectable defect, not a silent blank caption.
10. As a developer, I want the original karaoke painter extracted from `Main.tsx` into a `generic` renderer component, so that `pill`/`word-bold`/`kinetic` are just params of one registered renderer.
11. As a developer, I want `HighlightCaptions` ported into the project as the `highlight-box` renderer, so that the seed template becomes a first-class library entry.
12. As a creative-direction agent, I want to list available caption styles with their ids and human-readable descriptions, so that I can choose a feature-caption look without a hardcoded enum baked into my tooling.
13. As a creative-direction agent, I want to set a non-default style on a specific caption (a hook or emphasis moment), so that feature captions stand apart from base captions.
14. As the system, I want base captions auto-populated from the transcript with the brand kit's default caption style, so that the Director never has to author ordinary subtitles op-by-op.
15. As a future frontend, I want a standalone gallery composition per caption renderer with representative sample props, so that a user can see each visual and pick one.
16. As a developer, I want gallery compositions to derive their duration from `fps` + `duration_s` props the same way `stat_viz`/`motion_graphics` do, so that the preview path reuses the established pattern.
17. As a developer, I want a caption to render only the transcript-synced word reveal, so that the caption/callout boundary stays clean and non-synced annotations live elsewhere.
18. As a maintainer, I want the registry to be the single place that knows what each caption visual means, so that style knowledge is not scattered across the compiler, the backend, and the agent.
19. As a developer, I want the Python caption style registry to be a deep module with no render dependency, so that "this style compiles to these IR pieces" is unit-testable in isolation.
20. As a developer, I want the kinetic pop-in to keep riding the layer's opacity/scale keyframe tracks, so that the keyframe sampler — not per-style code in the generic renderer — drives that animation.
21. As a developer, I want `Caption.style` to accept any registered id, so that the composition model is open to new visuals without a code change to the kernel enum.
22. As a developer, I want clear failure when a caption references a style the renderer registry doesn't implement, so that a backend that lacks a renderer surfaces the gap rather than rendering nothing.

## Implementation Decisions

**Architecture (ADR 0010, amends ADR 0002).** Captions become the one place the backend dispatches on
a style name, via a registry. Every other IR layer kind (media, audio, transform overlays, layout)
stays neutral and name-agnostic per ADR 0002. This realizes the "per-plugin backend escape hatch"
ADR 0002 explicitly named as the growth path.

**Caption style registry (Python) — deep module.** Owns the only place that knows what each caption
style means. Interface:
- `get(id)` → the registered entry (description, param model, defaults, compile fn).
- `list()` → ids + descriptions, for agent discovery.
- `compile(id, params, start, end)` → the IR pieces for the layer (typed params + opacity/transform
  tracks + emphasis), generalizing today's `CompiledCaptionStyle`.
- Unknown id → error by default; skip-with-warning under `strict: false` (mirrors overlay-type
  handling).
Replaces the closed `CaptionStyle` enum, the `_PROPS`/`_EMPHASIS` dicts, and `compile_caption_style`.

**Caption renderer registry (TS) — deep module.** Maps `id → React caption renderer component`.
`Main.tsx`'s `TextLayerView` stops painting inline and instead looks up the layer's `style` id and
renders the matching component, passing the renderer contract. Unknown id → fallback (blank /
warning), never a crash.

**Renderer contract.** A caption renderer receives: the caption's `runs` (words + per-word spoken
`start`/`end`), the layer window (start/end), canvas + fps, and its own typed style params. It owns
phrase/box grouping, wrapping, and animation. It does **not** read brand-kit tokens (deferred —
explicitly not a "captions ignore the brand kit forever" decision, just out of scope).

**IR schema (`kernel/ir.py`).** `TextLayer` keeps `style` (now the registry id, authoritative — not
mere provenance) and carries typed `params`. The existing flat `TextStyle` becomes the param schema
of the `generic` renderer rather than a universal field. Kinetic's pop-in continues to ride the
layer `opacity`/`transform.scale` tracks evaluated by the shared keyframe sampler.

**Composition model (`kernel/composition.py`).** `Caption.style`: `CaptionStyle` enum → a
registry-validated string id (open key). A registered id is accepted; an unknown id errors (or warns
under `strict: false`). `CaptionWord` and the line-with-words shape are unchanged.

**Compile path (`compile_ir.py`).** Caption → text-layer compilation routes through the registry's
`compile(id, params, …)` instead of the hardcoded `compile_caption_style`.

**Built-in renderers.**
- `generic` — the karaoke painter extracted from today's `TextLayerView`; `pill`, `word-bold`,
  `kinetic` are configs (params) of it. Behavior-preserving for the three existing looks.
- `highlight-box` — `HighlightCaptions` ported into `project/src/captions/`, rendering the
  transcript word-reveal only (the seed's handwritten annotation/arrow is dropped — out of scope).

**Caption gallery (`Root.tsx`).** One standalone composition per renderer with representative sample
props, registered alongside `stat_viz`/`motion_graphics`, deriving duration from `fps` + `duration_s`
via the established metadata helper pattern.

**Agent integration (`tools.py`, `creative_direction.py`, prompts).** The agent's allowed caption
styles come from `registry.list()` (id + description) instead of the `CaptionStyle` enum, so a new
renderer is automatically selectable. Base captions take the brand kit's default caption style;
feature captions carry an agent-chosen id.

**Two-sided sync invariant.** The library has a Python half (schema/defaults/compile) and a TS half
(component). The set of ids must match across the boundary; a divergence is a defect to be caught,
not tolerated.

## Testing Decisions

A good test here asserts **external behavior through the module's interface**, not its internals: feed
a caption style id + params + window and assert the compiled IR pieces; feed a Composition and assert
the resulting IR; feed an id to the registry and assert lookup / error semantics. Tests must not
assert private dict shapes or component implementation details. Prior art: existing
`plugins/captions` style tests, `compile_ir` tests, and composition validation tests — mirror their
structure and helpers.

Modules to test (all four):
- **Python caption style registry** — `get`/`list`/`compile`; unknown-id error vs skip-with-warning
  under `strict: false`; each built-in style compiles to the expected IR pieces (generic params for
  `pill`/`word-bold`/`kinetic`, kinetic's opacity/scale keyframes, `highlight-box` params). Highest
  value — pure logic, no render dependency.
- **`compile_ir` caption path** — a Composition mixing caption styles compiles to a valid IR whose
  `text` layers carry the right `style` id and params. Mirrors existing `compile_ir` tests.
- **TS caption renderer registry** — registry lookup resolves a known id to its component; an unknown
  id hits the fallback rather than throwing. Visual rendering itself is verified via the gallery, not
  asserted here.
- **Composition `Caption.style` validation** — accepts a registered id; rejects an unknown id (or
  warns under `strict: false`). Mirrors existing composition validation tests.

## Out of Scope

- **Brand-kit theming of captions.** Renderers are self-contained for now; wiring brand tokens
  (color/font/highlight/safe-zone) into caption renderers is deferred.
- **The handwritten annotation + arrow** from the seed template. Not transcript-synced, so not a
  caption; it will live in a future callout/overlay concern.
- **New caption visuals beyond `highlight-box`.** The library is built to add more cheaply later;
  this PRD ships the migration + one net-new renderer, not a catalog.
- **The frontend picker UI itself.** This PRD provides the gallery compositions the picker will
  consume, not the picker.
- **Non-Remotion backends' caption renderers.** A second backend would implement its own renderers
  for the same ids; not built here.
- **Changes to how base captions are auto-populated from the transcript.** The default-style wiring
  is honored, but the transcription→captions pipeline is assumed to exist.

## Further Notes

- ADR 0002 line 11 already anticipated this exact move ("Hybrid: IR + per-plugin backend escape
  hatch — the growth path if an exotic effect ever exceeds the IR vocabulary"). ADR 0010 records
  taking it for captions.
- The caption style registry is intentionally shaped like the existing **overlay registry**
  (`type → {param schema, defaults, renderer}`) so the two share one mental model.
- Suggested first tracer-bullet slice: `highlight-box` end-to-end — register on both sides → IR
  dispatch in `Main.tsx` → one gallery composition — proving the full vertical before migrating the
  three existing styles.
