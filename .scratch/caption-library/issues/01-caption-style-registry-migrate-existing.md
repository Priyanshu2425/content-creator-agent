# Caption style registry + migrate existing styles

Status: ready-for-agent

## Parent

`.scratch/caption-library/PRD.md`

## What to build

The tracer-bullet vertical slice that stands up the **caption library** end-to-end and migrates the
three existing looks onto it, with **no visible change** to how `pill`/`word-bold`/`kinetic` render.

Establish the **caption style registry** as the single place that knows what each caption visual
means, on both sides of the Python/Remotion boundary:

- **Python (deep module):** a registry with `get(id)`, `list()` (ids + descriptions), and
  `compile(id, params, start, end)` returning the IR pieces for the layer (typed params +
  opacity/transform tracks + emphasis), generalizing today's `CompiledCaptionStyle`. Replaces the
  closed `CaptionStyle` enum, the `_PROPS`/`_EMPHASIS` dicts, and `compile_caption_style`. An unknown
  id is an error by default, downgraded to skip-with-warning under `strict: false` (same rule as an
  unknown overlay type).
- **TS (deep module):** a registry mapping `id → React caption renderer component`. The IR
  interpreter (`Main.tsx`'s text-layer path) stops painting inline and dispatches by `id` to the
  matching component; an unknown id hits a safe fallback, never a crash.

Reshape the seam so a `text` layer carries its `style` id (now authoritative, not provenance) + typed
`params`; the existing flat `TextStyle` becomes the param schema of the `generic` renderer rather
than a universal field. `compile_ir` routes caption compilation through the registry. `Caption.style`
becomes a registry-validated open key instead of a closed enum.

Migrate the three existing styles into a single **`generic`** caption renderer (the karaoke painter
extracted from today's text-layer view); `pill`/`word-bold`/`kinetic` are configs (params) of it.
Kinetic's pop-in keeps riding the layer's `opacity`/`transform.scale` tracks evaluated by the shared
keyframe sampler — no per-style animation code in the renderer.

Agent tooling is intentionally left untouched in this slice: it still emits the three ids, which
remain valid registry keys, so authoring keeps working. Registry-driven discovery is a later slice.

The Python and TS halves are two synchronized halves of one library: the set of registered ids must
match across the boundary.

## Acceptance criteria

- [ ] A Python caption style registry exposes `get`, `list` (id + description), and `compile`; the old enum / `_PROPS` / `_EMPHASIS` / `compile_caption_style` are gone.
- [ ] An unknown caption style id raises by default and is skipped-with-warning under `strict: false`.
- [ ] `TextLayer` carries a `style` id + typed `params`; `compile_ir` produces caption text layers through the registry.
- [ ] `Caption.style` accepts any registered id and rejects an unknown one (warns under `strict: false`).
- [ ] A TS caption renderer registry resolves a known id to its component and falls back safely on an unknown id; `Main.tsx` dispatches through it.
- [ ] `pill`, `word-bold`, and `kinetic` are configs of one `generic` renderer and render identically to before (regression-verified), including kinetic's pop-in via the keyframe tracks.
- [ ] Unit tests: Python registry (`get`/`list`/`compile`, unknown-id error vs strict skip, each built-in style compiles to expected IR pieces). Mirrors existing `plugins/captions` style tests.
- [ ] Integration tests: a Composition with mixed caption styles compiles to a valid IR with correctly-keyed text layers. Mirrors existing `compile_ir` tests.
- [ ] Unit tests: `Caption.style` accepts registered ids, rejects unknown (or warns under `strict: false`). Mirrors existing composition validation tests.
- [ ] Lightweight TS test: renderer registry lookup resolves a known id and falls back on an unknown id.

## Blocked by

None - can start immediately.
