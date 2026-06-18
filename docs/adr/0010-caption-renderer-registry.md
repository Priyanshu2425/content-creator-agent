# Caption renderer registry (the caption library)

A **caption style** is no longer a closed three-value enum baked into flat IR props. It is a registered entry `{id, description, param schema, defaults, renderer}` in a **caption style registry**. A `text` layer in the IR carries its style `id` + typed params + word `runs`; the Remotion backend dispatches the layer to a **caption renderer** (a React component) looked up by `id`. This is the single point where the backend branches on a style name.

This **amends ADR 0002** for captions only. ADR 0002 keeps holding for media, audio, transform overlays, and layout: those stay flat IR primitives the backend interprets without knowing names. ADR 0002 already anticipated this as the "per-plugin backend escape hatch ... the growth path if an exotic effect ever exceeds the IR vocabulary" — captions are the first place that growth path is taken.

We chose this because the flat `TextStyle` vocabulary (font/color/background/radius/padding/highlight + opacity/scale keyframes) provably cannot express the caption visuals we want — e.g. `highlight-box`: words split into separate wrapping highlighter boxes, per-box rotation jitter, per-word spring pop. These are irreducibly component-shaped, not prop values. The requirement is an *extensible library* ("easily add caption visuals later"), and a future frontend gallery where a user picks a visual — both of which want one component per visual, registered and discoverable, reused across the IR render path and the standalone preview compositions.

## Considered options

- **Flat-props only (keep ADR 0002 pure for text)** — every style compiles to the existing `TextStyle` + keyframe primitives. No backend branch. Rejected: cannot express `highlight-box` or anything structurally beyond recolored centered text; caps the library to the dead end the seed template already exceeds.
- **Two-track (legacy flat + new registry)** — `pill`/`word-bold`/`kinetic` stay on the untouched flat renderer; only new rich visuals use the registry. Rejected: two caption code paths and two ways to add a style, forever.
- **Caption renderer registry, uniform (chosen)** — every style, including the original three, is a registry entry. The original generic karaoke look becomes one renderer that `pill`/`word-bold`/`kinetic` configure via params; `highlight-box` is a second renderer. One dispatch path, one way to add a style.

## Contract

- A caption renderer receives: the caption's `runs` (words + per-word spoken `start`/`end`), the layer window, canvas + fps, and its own typed style params. It owns its phrase/box grouping and animation.
- It does **not** read brand-kit tokens. Caption visuals are self-contained for now; brand-kit conformance for captions is deliberately deferred (it is *not* a settled "captions ignore the brand kit" decision — just out of scope here).
- Captions render only the transcript-synced word reveal. Non-synced callouts (the seed template's handwritten annotation + arrow) are out of scope for a caption renderer and will live elsewhere (a callout overlay / the existing title overlay).

## Consequences

- The backend now has one name-keyed dispatch (captions). Every other layer kind stays neutral. The registry must exist on both sides: a Python entry (param schema + defaults, for validation and `compile_ir`) and a TS entry (`id → component`); the two must stay in sync, and an `id` present on one side but not the other is a defect.
- An unknown caption style `id` is an error by default, downgraded to skip-with-warning under `strict: false` — same rule as an unknown overlay `type`.
- Adding a caption visual = drop a renderer component + register it on both sides (+ a gallery composition). It never touches the core IR schema or any other backend layer.
- The creative-direction agent discovers available styles by reading the registry (`id` + `description` + gallery preview), not a hardcoded enum, so a new visual is automatically selectable.
- A non-Remotion backend must implement its own caption renderers to honor the same `id`s, or it cannot render captions. This is the accepted cost of exceeding the neutral vocabulary.
