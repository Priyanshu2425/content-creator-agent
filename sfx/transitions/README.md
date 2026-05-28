# sfx/transitions/

Global folder for transition sound effects used by the render pipeline.

## whoosh cut

Drop your whoosh/swish audio file here. Recommended filename: `whoosh.mp3` (or `.wav`).

The file is played as a hard-cut audio accent at every scene boundary marked with
`kind: "whoosh"` in the Composition. It should be short (0.2–0.5s), centered on the
cut point, and mixed at a level that accents the cut without overpowering the voiceover.

Once the file is in place, wire the path into `compile_ir._apply_transitions` where the
TODO comment is — it will emit an `AudioLayer` spanning roughly `[cut - duration/2, cut + duration/2]`
so the swoosh straddles the boundary.
