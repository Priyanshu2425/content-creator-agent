# Director dispatches specialist workers in-loop while still authoring via Builder ops

The former authoring agent becomes the **Director**: it still authors the Composition by calling
**Builder operations one at a time**, each validated immediately ([0004](./0004-tool-driven-incremental-authoring.md)
holds), but its tool surface now also includes **worker-dispatch tools** (`dispatch_broll`,
`dispatch_text_hook`, `dispatch_sfx`) alongside the Builder ops. A dispatch runs a specialist worker
agent and returns its **proposal** (ranked hook candidates, a b-roll shot list, an SFX placement
list) as a tool result, which is threaded back into the Director's perception; the Director then
turns the accepted parts of that proposal into Builder ops. Workers return proposals only — the
Director remains the **single agent that authors the document and composites** (ADR
[0002](./0002-neutral-render-ir-swappable-backends.md)'s neutral IR is untouched).

We chose in-loop dispatch over the two obvious alternatives. **Fixed pre-loop pipeline stages** (the
old shape: run every specialist unconditionally, then author) make the Director an orchestrator in
name only — the pipeline decides, not the model — and cannot skip a worker a video doesn't need,
re-dispatch a weak proposal, or sequence a worker (SFX) after the visuals it depends on. **Letting
the Director emit one master Composition JSON** (as the brainstorming docs imagined) would throw away
the per-op validation and self-correcting loop that is the most valuable thing the kernel has. In-loop
dispatch keeps [0001](./0001-declarative-scene-overlay-model.md)/[0004](./0004-tool-driven-incremental-authoring.md)
intact while letting the model genuinely decide what specialist help each video needs.

## Consequences

- **Two budgets.** Builder ops keep their existing operation budget; worker dispatches draw from a
  separate, small per-worker dispatch budget (a single dispatch is expensive and must not starve
  authoring turns or run away by re-dispatching).
- **Workers never composite or certify.** A worker may call Remotion to render *standalone asset
  clips* (e.g. the b-roll worker's stat-viz), but final compositing is the Director's alone — so two
  agents never fight over z-order, safe zones, or timing.
- **The Director owns cross-layer state** the workers cannot see: the locked **brand kit**, the
  **timeline skeleton** (the former IdealCuts planning, folded in), and **pacing** reconciliation read
  off the Resolver timeline. Pacing is Director *behavior* in v1, not kernel-enforced.
- The system stays multi-agent and multi-model: the Director (text/tool), the workers (per-specialty),
  and the unchanged video-capable review sub-agent from [0004](./0004-tool-driven-incremental-authoring.md).
