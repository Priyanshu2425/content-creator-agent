# Tool-driven incremental authoring with structured + vision feedback

The Agent does not emit a Composition in one shot. It calls **Builder operations** one at a time (`addScene`, `fillRegion`, `addOverlay`, `addCaption`, …); each operation is **validated immediately** and errors are fed back; the accumulated result *is* the declarative Composition. The Agent perceives a **Media Manifest** (assets, durations, transcript with word timings) up front, and after each op the current Composition + validator errors + a **Resolver** textual timeline. While building, it can request **on-demand vision** — a **still frame** at `t` (via the backend's fast `render_still`) or a **scene preview** (an image strip of one scene) — to *see* its work without rendering on every op.

We chose incremental tool use over **one-shot JSON generation** because LLMs reliably produce large, invalid JSON that is hard to localize and repair; per-operation validation makes the loop self-correcting. In-loop vision is agent-triggered (not every-op) so the authoring agent controls render cost.

**Finalization is gated by a separate review sub-agent.** Rather than the authoring agent sampling stills at the end, a dedicated **video-capable LLM** (behind a `ReviewAgent` interface) natively watches the full `render_video()` output and returns timestamped feedback (caption sync/occlusion, pacing, framing). The authoring agent applies the edits, re-renders, and re-reviews — capped at N rounds (default 2) — then ships. Image-based stills/scene-previews remain the *in-loop* channel; full-motion judgement is the review sub-agent's job.

## Consequences

- There is an **imperative authoring API** (the Builder ops) that compiles into the **declarative runtime model** — note the deliberate inversion from [0001](./0001-declarative-scene-overlay-model.md): imperative is fine for *authoring* (a builder), just not for *runtime state* (which stays derived).
- The Builder, Validator, and Resolver live in the shared kernel so AuthoringService stays free of render dependencies.
- Backends must support a cheap `render_still(t)` (in-loop stills/scene-previews), not only `render_video()` (which the review sub-agent consumes).
- Finalization uses a **video-capable review sub-agent** (`ReviewAgent`), distinct from the text/tool authoring agent — the system is multi-model (authoring LLM + video-review LLM).
