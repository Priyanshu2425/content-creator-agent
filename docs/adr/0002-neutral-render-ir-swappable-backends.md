# Neutral render IR with swappable backends

RenderService does not render a Composition directly. The Composition (with each plugin's `toIR(params)`) compiles to a **backend-agnostic render IR** — timed layers of primitives: media, transform keyframes, text runs + styles, opacity, mask, z. Each **backend** implements `IR → frames`. Remotion is the first backend (a Python class shelling out to a Node/Remotion CLI); `FfmpegBackend` and custom engines are swappable by writing one new IR interpreter. Backends expose both `render_video()` and a fast `render_still(t)`.

We chose this because "swap the renderer" was an explicit requirement, and it is only real if a backend swap does **not** rewrite every plugin. With an IR, plugins are backend-agnostic and the swap is a single interpreter; the heavy render code (Remotion/ffmpeg) lives only in the backend, so a plugin's render facet stays pure data and can sit in the shared kernel with zero render dependencies.

## Considered options

- **Per-backend plugin impls** (`zoom.remotion`, `zoom.ffmpeg`, …) — unlimited per-effect expressiveness, but swapping a backend requires every plugin to support it (an NxM capability matrix). Rejected as the default.
- **Call Remotion directly, no IR** — simplest now, but "swappable" becomes fiction: every plugin is tied to Remotion. Rejected.
- **Hybrid (IR + per-plugin backend escape hatch)** — the growth path if an exotic effect ever exceeds the IR vocabulary.

## Consequences

- Effects are limited to what the IR vocabulary can express. The known surface (zoom, pan, insert, captions, kinetic text) fits cleanly; a novel effect may require extending the IR, which touches all backends.
- Adding an action stays a one-plugin-folder change (`contract` + `toIR`); it never touches a backend.
