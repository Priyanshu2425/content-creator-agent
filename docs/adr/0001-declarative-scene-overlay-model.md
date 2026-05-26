# Declarative scene + overlay model, not an imperative action stream

The video is described as **declarative scenes** (an ordered base layer of layout-bearing time spans) plus a **registry-extensible overlay union** (captions, transforms like `zoom`/`pan`, and additive `insert`s) — all placed on one absolute-seconds timeline whose master clock is the continuous voiceover. On-screen state is **derived per-frame** (the scene covering `t` + the overlays active at `t`), never replayed.

We chose this over the originally-proposed **imperative action-stream** (a timeline of `setLayout`/`show`/`zoom` commands mutating a running state). Replay-based state is fragile to edit (insert one action and everything downstream shifts), hard to seek (must replay 0→t to know what's on screen), and hard to validate. The declarative model makes state total and order-independent.

## Considered options

- **Imperative action stream** — intuitive to write, but fragile to edit/seek/validate. Rejected.
- **Flat declarative element soup** — every element carries its own time range, no "scene" unit. Robust but loses the shot as a first-class authoring unit. Folded in as the overlay layer.
- **Scene-based hybrid (chosen)** — scenes capture the shot sequence creators think in; overlays/captions ride on top as declarative timed layers.

## Consequences

- Adding a new action = registering a new overlay `type` (param schema + defaults + renderer) in the overlay registry; the core envelope schema is untouched. Documents carry a `version`; unknown types error under `strict: true`, skip-with-warning otherwise.
- "Maintain current state" stops being a problem to solve — there is no mutable state to maintain.
- Effect targets are spatial frame regions (`full`/`top`/`bottom`), and transitions key off stable scene ids — both chosen to avoid positional/temporal coupling that would re-introduce replay-style fragility.
