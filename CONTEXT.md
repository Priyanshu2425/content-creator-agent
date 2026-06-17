# Short-Form Video Composition Format

A JSON document that declaratively describes a vertical (9:16) short-form video — talking-head + b-roll + synced captions — so the edit can be driven entirely from data. This glossary fixes the language; it is not a spec.

## Language

**Composition**:
The whole JSON document — one video. Holds the base scene layer plus the declarative overlay layers.

**Scene**:
A contiguous span of the video that owns the **base layer** during its time: it sets the layout and decides which item fills each region. Carries a stable `id` (referenced by transitions). Scenes are the main visual cuts (split-screen hook, full host, cut to b-roll). At any instant exactly one scene is on the base layer.
_Avoid_: shot, clip, segment

**Overlay**:
An independently-timed thing layered *on top of* scenes, carrying its own start/end (captions, effects, floating inserts). Overlays do not belong to a scene and may cross scene boundaries.
_Avoid_: element, layer, widget

**Voiceover**:
The continuous primary audio (the host's speech). It is the **master clock** — it plays straight through scene cuts and defines the composition's duration.
_Avoid_: audio, narration, VO (as the canonical term)

**Timeline**:
The single axis on which everything is placed, measured in **absolute seconds** from 0. Scenes, overlays, and captions all carry `start`/`end` in seconds. Transcript word-timings, if used, compile down to seconds — seconds stay canonical.

**Layout**:
A named arrangement drawn from a built-in **layout registry** (e.g. `full`, `split-h`). Each layout exposes a fixed set of named **region** slots. A scene picks one layout. New arrangements (left/right, PiP) are added by registering a new preset — no schema change. Geometry is owned by the preset, not written per-scene (no free-form rects).
_Avoid_: template, view, mode

**Region**:
A named slot exposed by a layout (`full`; or `top` + `bottom` for `split-h`) that a scene fills with one item. The `split-h` divider defaults to 50/50, adjustable via `ratio`.
_Avoid_: zone, area, half, panel

**Asset**:
A reusable media source declared once in the top-level library (`id → {type, src}`); types are `video`, `image`, `audio`. Referenced by id everywhere it appears.
_Avoid_: media, file, clip, source

**Reference**:
How a scene region (or overlay) points at an asset. May carry an **in-point** (`in`) — the source-time offset where playback begins — so one long recording can be jump-cut across many scenes. The slice's on-screen duration comes from the holding span, not the asset.
_Avoid_: clip, instance

**Caption**:
A transcript-synced text cue on the dedicated `captions` track — carries `text`, `start`/`end`, and a **caption style**. Kept off the overlays list because captions are voluminous and homogeneous.
_Avoid_: subtitle, text overlay, title

**Caption style**:
A named preset controlling a caption's appearance. Three known: `pill` (dark rounded normal speech), `word-bold` (plain white emphasis word), `kinetic` (large pop-in key word).
_Avoid_: caption type, font

**Overlay type**:
The discriminator on an overlay entry, resolved through an **overlay registry** mapping `type → {param schema, defaults, renderer}`. Built-ins include `zoom`, `pan`, `insert`. Adding a new action = registering a new type; the core schema is untouched.
_Avoid_: action kind, effect name

**Envelope**:
The type-agnostic fields every overlay shares (`type`, `start`, `end`, `region`/target). Validated by the fixed **core schema**; the type-specific params are validated separately by `registry[type]`. Two-phase validation.
_Avoid_: base, common fields

**Version / strict mode**:
The composition carries a top-level `version` (schema version). An unknown overlay `type` is an **error** by default; `strict: false` downgrades it to skip-with-warning so a newer doc degrades gracefully on an older renderer.
_Avoid_: schema id, mode

**Transform overlay vs additive overlay**:
A **transform overlay** (`zoom`, `pan`) reshapes its target *base region* and is not painted — it never scales the layers above it. An **additive overlay** (`insert`, and captions) is painted on top. Only additive things participate in the paint stack.
_Avoid_: filter vs sticker

**z (paint order)**:
A single explicit ordering space shared across **overlays and captions** (no implicit defaults; convention is high `z` for captions so text stays on top). Orders only painted (additive) things; a transform overlay's `z` does not pull painted layers into its transform.
_Avoid_: layer, depth, priority

**Target (region)**:
How an effect overlay names what it acts on: a **frame region** (`full`/`top`/`bottom`), purely spatial and resolved against the frame — never by scene index or asset. `full` is always valid; layout-specific regions (`top`/`bottom`) are valid only while a scene exposing them is active.
_Avoid_: scene reference, selector

**Transition**:
What happens at a scene boundary. The default is a hard **cut** and is never written. The `transitions` array is **sparse** — it lists only non-cut boundaries (e.g. `crossfade`), each keyed by the scene it follows (`afterScene: <id>`), never by absolute time. Cut is not an entity you author.
_Avoid_: dissolve (as the general term), wipe, cut object

## Composition model (resolved)

Two layers, combined:
- **Scenes** = base layer, persistent layout state, ordered spans. Answers "what fills the frame."
- **Overlays** = declarative timed layer on top, each self-contained. Answers "what's added on top, when."

State is *derived* from (current scene + active overlays at time t), never replayed. Rejected: pure imperative action-stream (fragile to edit/seek).

**Coverage rules**: scenes may **not overlap** (validation error). **Gaps are allowed** and render as black — the voiceover keeps playing and overlays/captions still composite over the black. A gap should raise a validator *warning* (catch accidental ones) but not an error. Composition duration is set by the voiceover; a trailing gap is a black tail.

## B-roll boundary (resolved)

Both forms are first-class, author picks per shot:
- **Full-frame b-roll** = a `full` **scene** with the screenshot as its region item (hard cut in/out). This is the reference-video style.
- **Floating b-roll** = an `insert` **overlay** (a card over a continuing scene, positioned by `anchor`/`scale`, painted by `z`).

## Agents (resolving)

**Director**:
The orchestrator agent — the former *authoring agent*, renamed. Owns everything that must be consistent across the whole video and integrates worker outputs into the finished Composition. It still authors the Composition by calling **validated Builder ops one per turn** (the kernel stays the source of truth; the Director never emits a Composition JSON wholesale — ADR 0001 holds). New power: it dispatches worker agents and turns their accepted **proposals** into op calls.
_Avoid_: authoring agent (old name), orchestrator-as-author

**Worker**:
A specialist sub-agent the Director dispatches. A worker returns a **proposal** (candidates / a list / intents) — never a Composition and never a rendered final. The Director decides what to accept and is the only agent that authors the document. Three workers: `TextHookAgent`, `BrollGeneratorAgent`, `SFXAgent`.
_Avoid_: sub-agent (informal), tool (a worker is dispatched, not a Builder op)

**Proposal**:
What a worker returns to the Director — e.g. ranked text-hook candidates, a b-roll shot list, an SFX placement list. Advisory: the Director may accept, drop, or amend before it becomes ops. Distinct from the doc the Director builds.

**Brand kit**:
The locked, per-video token spec the Director owns and injects to every worker — the single source of truth for the video's design language (colors, font, caption style, sfx palette + density budget, frame meta, and safe-zone tokens in v1; motion/graphics/logo/sound tokens grow in later phases). Safe-zone tokens are reasoned with *behaviorally* by the Director in v1 (no machine enforcement yet). Workers style every asset to these tokens; an asset that ignores them is non-conformant. Supersedes the hardcoded `StyleBrief` seed.
_Avoid_: theme, style guide, design system

**Brand profile**:
The optional user-supplied *input* the brand kit is built from. If present the Director loads it; if absent the Director derives a sensible kit from the brief. Once built, the kit is locked for the whole video.
_Avoid_: brand kit (the profile is the input; the kit is the locked result)

**Text hook**:
The on-screen static headline overlaid on the first ~1–3s, for the muted scroller and the paused thumbnail. Produced by `TextHookAgent`. Distinct from the **spoken hook** (the creator's opening line, already recorded, never changed) and from a **caption** (transcript-synced, animated). Placed by the Director as a new additive `title` overlay (not a caption).
_Avoid_: title card, caption, subtitle

**Spoken hook**:
The first line(s) the creator actually says, already in the recording. The text hook must say something *different but consistent* — a second angle, never a transcript of the spoken hook.

## Flagged ambiguities

- **"Action"** is the user's umbrella word. Canonically it splits into an **overlay** (anything on top of scenes), a **scene** boundary, and a **transition**. There is no single "action" entity.
