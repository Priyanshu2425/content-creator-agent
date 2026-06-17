# SFXAgent is the single SFX authority; the whoosh transition loses its built-in sound

Sound effects were split across two uncoordinated mechanisms: the post-authoring `AudioDeciderAgent`
annotated every scene cut with a sound, while the kernel's `whoosh` **transition** separately bundled
its own whoosh SFX accent — so a whoosh transition and an AudioDecider whoosh could double-fire on the
same cut. We make the **SFXAgent** (the recast `AudioDeciderAgent`, now a Director-dispatched worker —
see [0008](./0008-director-dispatches-workers-in-loop.md)) the **single SFX authority**, and we
**decouple the `whoosh` transition's built-in sound**: the transition becomes a purely *visual*
smash-cut, and any whoosh *sound* is placed by the SFXAgent. The Director owns the typed
**event timeline** it passes to the worker; the worker does only the emphasis-selection and density
judgment and returns a placement proposal — it certifies nothing.

We chose single-authority-with-decoupling over keeping the two mechanisms split (the lower-churn
option). Two authorities guarantees drift and double-firing forever and leaves SFX as a decision the
Director cannot make in context. The cost we accept is real: decoupling changes existing render
behavior and breaks snapshot tests that expected the whoosh transition to emit an audio node — which
is exactly why this is worth recording, so a future reader doesn't "restore" the transition's sound
and reintroduce the double-fire.

## Consequences

- **A `whoosh` transition produces no audio node** — snapshots are updated to pin this. Visual and SFX
  layers are now fully independent.
- **The deterministic event classification moves out of the worker** into a pure event-timeline
  builder the Director runs over the assembled composition; the worker receives typed events rather
  than inferring them.
- **v1 stays cut-bound** (SFX binds via the existing `scene.audio` path that already renders) and uses
  the three real palette sounds (`click`/`whoosh`/`dramatic_whoosh`). Free-timestamp SFX and the
  larger palette are deferred.
- The palette and density budget live on the locked **brand kit**, so SFX draws from the same source
  of truth as every other layer.
