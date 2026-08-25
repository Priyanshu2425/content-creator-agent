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
A transcript-synced text cue on the dedicated `captions` track — carries `text`, `start`/`end`, and a **caption style**. Kept off the overlays list because captions are voluminous and homogeneous. A caption renders only the transcript-synced word reveal; non-synced callouts (handwritten notes, arrows) are *not* captions (see **text hook**, and the future callout overlay).
_Avoid_: subtitle, text overlay, title

**Base caption**:
The default transcript-synced subtitle. The `captions` track is populated **in bulk** from the transcript word-timings — *not* authored one caption at a time — and every base caption takes the brand kit's **default caption style**. Both pipelines produce the same track: the director-loop fills it on the Director's instruction; the chain fills it deterministically in its **reconcile step**. A composition with no base captions is a defect, not a style choice.
_Avoid_: subtitle, default caption (as the canonical term)

**Feature caption**:
A caption the Director / creative-direction agent places deliberately for a hook or emphasis moment, with a chosen non-default **caption style**. Same entity as a base caption (one `Caption`); the distinction is *who set the style and why*, not a different type.
_Avoid_: custom caption, hook caption

**Caption style**:
A registered entry `{id, description, param schema, defaults, renderer}` controlling one caption visual. Resolved through the **caption style registry** exactly as an **overlay type** is resolved through the overlay registry — `id` is an open registry key (validated against the registry; unknown id errors, or skip-with-warning under `strict: false`), *not* a closed enum. Built-ins: `pill`, `word-bold`, `kinetic` (the original generic karaoke look, now configs of one renderer), `highlight-box` (neon highlighter boxes with per-word pop), and `tiktok` (a port of Remotion's TikTok template — heavy text with a thick black stroke, a line pop-in, and the spoken word recoloured bright green; the current default). Adding a visual = register a new entry; the core schema is untouched.
_Avoid_: caption type, font, caption preset

**Caption renderer**:
The React component that paints one caption style's visual (e.g. `HighlightCaptions`). It receives the caption's words with their spoken windows (`runs`), the layer window, canvas + fps, and its own typed **caption style** params — and owns its own phrase/box grouping and animation. It does *not* read brand-kit tokens (deferred). The same component serves both the IR render path and the caption gallery.
_Avoid_: caption widget, caption view

**Caption style registry**:
The map `caption style id → caption style entry` — the "caption library." The single place that knows what each caption visual means. The Remotion backend dispatches a `text` layer to a caption renderer through this registry; this is the one place the backend branches on a style name (ADR 0010 amends ADR 0002 to permit it for captions only).
_Avoid_: caption library (informal), caption map

**Caption gallery**:
The set of standalone Remotion compositions (registered in `Root.tsx`, alongside `stat_viz`/`motion_graphics`) that preview each caption renderer with sample props. Bypasses the IR; exists so a future frontend can show the user each visual and let them pick. Built from the same caption renderer components the IR path uses.
_Avoid_: caption preview, caption demo

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
A specialist sub-agent the Director dispatches. A worker returns a **proposal** (candidates / a list / intents) — never a Composition and never a rendered final. The Director decides what to accept and is the only agent that authors the document. Workers: `TextHookAgent`, `BrollGeneratorAgent`, `SFXAgent`, `CreativeDirectionAgent`, `MotionGraphicsAgent`. A worker may have an alternate **ToT variant** (a deliberating implementation selected by a `tot_enabled` flag) that returns the same proposal shape — the Director's dispatch contract is identical either way.
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

**Payoff frame**:
A candidate interpretation of *what the viewer gets* from the video — e.g. literal/practical, emotional/identity, or contrarian/myth-busting. A transcript usually supports more than one. The chosen frame is upstream of and determines which text hooks are even possible, so it is the substance a hook is built on (not its tone). A deliberating `TextHookAgent` weighs several frames before committing.
_Avoid_: angle (too vague), payoff (the payoff is the thing gained; the frame is the interpretation of it)

**Creative concept**:
The governing visual strategy a piece of creative direction commits to — the core metaphor + treatment that the hook, b-roll map, pacing, and CTA all answer to. The `CreativeDirectionAgent`'s upstream analogue of a payoff frame: several legitimate concepts exist per transcript, and the chosen one dictates the whole downstream execution.
_Avoid_: theme, idea, direction (the *direction* is the finished document; the *concept* is the strategy it commits to)

## Pipelines (resolving)

**Pipeline**:
The end-to-end walk from a host recording + brief to a finished mp4. The shared front half (ingest → transcribe → ideal-cuts) is identical for every run; the back half (how the Composition is authored) is chosen by a **pipeline strategy**. Selected per run via `make --pipeline {director-loop, chain}`.
_Avoid_: flow, run (a run is one execution of a pipeline)

**Director-loop pipeline**:
The default (ADR 0008). After the shared front half, the **Director** authors the Composition by *pulling* workers on demand — the model decides which specialist to dispatch, when, and turns each accepted proposal into validated Builder ops one per turn. Adaptive: it can skip a worker, re-dispatch a weak proposal, or sequence a worker after the visuals it depends on.
_Avoid_: default pipeline (informal), authoring loop (old name for the loop inside it)

**Chain pipeline**:
The fixed-order alternative (ADR 0013) that *coexists* with the director-loop pipeline and shares the same workers. After the shared front half it runs creative direction → { broll, motion-graphics, text hook } (parallel) → prep → **Composer** → SFX → render. The *pipeline* decides dispatch, not a model — there is no adaptive Director. Exists to A/B the topology (fixed order + single integrator) against the loop with the workers held constant.
_Avoid_: linear pipeline, chain mode

**Pipeline strategy**:
The swappable object that owns a pipeline's back half behind the shared front half. `DirectorLoopStrategy` (default) or `ChainStrategy`. The fork seam sits after ideal-cuts.
_Avoid_: pipeline type, mode

**Composer**:
The chain pipeline's terminal agent — *not* the Director. A single **no-tools Opus 4.8 Claude Code SDK** call that emits a **Composition directly** (Composition-layer authoring, above the kernel; it never authors a kernel op). It does **LLM-decided placement** from a deterministically prepared bundle of time-anchored `(Beat, Asset|None)` pairs, deciding only region / layout / treatment / gap-fill. Knowingly opts out of the Director's deterministic placement (ADR 0012 `execute()`) for the chain pipeline only. Guarded by an inviolable *no wrong-role back-fill* rule (asserted post-hoc) and the IR validator (bounded re-prompt on failure).
_Avoid_: director (the chain has no Director), assembler, integrator, builder

**Prep step**:
The deterministic (no-model) stage between the chain's workers and the Composer. Two lookups: **zip** each beat to its asset by `beat_id` (a missing asset → an explicit `None` pair) and **resolve** each beat's word-index `transcript_span` to concrete `[start_s, end_s]` from the transcript word-timings. Hands the Composer time-anchored `(Beat, Asset|None)` pairs so the LLM never does beat↔asset matching or timestamp arithmetic.
_Avoid_: prepare, join step, binder

**Reconcile step**:
The deterministic (no-model) stage **after** the Composer in the chain — the mirror of the **prep step**. It applies the corrections that are pure functions of ground truth, not judgment: filling the **base captions** track from the transcript word-timings in the brand kit's style, and **animating** any still held longer than the static-image limit with a slow zoom (animate, never shorten — the voiceover master clock fixes spans). Things the Composer is *not* asked to do because they are mechanical, not creative.
_Avoid_: post-process, cleanup, finalize (which is the separate review gate)

## Flagged ambiguities

- **"Action"** is the user's umbrella word. Canonically it splits into an **overlay** (anything on top of scenes), a **scene** boundary, and a **transition**. There is no single "action" entity.
