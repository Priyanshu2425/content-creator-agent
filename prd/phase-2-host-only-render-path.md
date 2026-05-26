# Phase 2 — Host-Only Render Path

## Problem Statement

Phase 1 produced the Pydantic contract types for the **Composition** and the neutral render **IR**, with round-trip and validation unit tests. Those types are inert: nothing yet turns a Composition into a watchable video. The riskiest seam in the entire system is the boundary where Python compiles a Composition into the neutral IR, hands that IR to a Node/Remotion subprocess as JSON props, and gets back an mp4. This seam crosses a language boundary (Python ↔ JS), a process boundary (subprocess invocation of the Remotion CLI), and a representation boundary (Composition → IR → frames), and each of those boundaries is a place where an incorrect assumption about timing, units, asset resolution, or audio muxing can silently corrupt the output.

We cannot validate the rest of the build order — captions, layouts, b-roll, effects, the authoring agent — until that seam is proven on the simplest possible case. The simplest case is a single host-cam recording rendered straight through: the host's audio is the **voiceover** and master clock, the host's video fills the frame for the whole duration, and there are no captions, no overlays, no transitions, and no second asset. If we can take a raw host recording and emit an mp4 whose duration matches the recording and whose frames show the talking head, we have de-risked the Python↔Remotion↔IR seam and earned the right to layer everything else on top.

This phase exists purely to make that single, vertical slice work end to end. It deliberately does the minimum at each layer — a minimal **MediaService**, a hand-written single-Scene Composition, a minimal `compile_ir` that only knows the `media` Layer kind, a minimal Remotion `project/` that only mounts media plus audio, and a `RemotionBackend` that drives the Remotion CLI. The payoff is a working, inspectable render pipeline and a known-good fixture that every later phase extends rather than reinvents.

## Solution

We build the thinnest end-to-end render path that produces an mp4 from a host recording, touching one representative piece of each layer the full system will use.

**MediaService (facts only, per ADR 0003).** We stand up a minimal MediaService that ingests a host recording, probes it with `ffprobe` via subprocess to extract objective facts (duration in seconds, pixel dimensions, frame rate), assigns the recording a stable **Asset** id, and resolves that id to a filesystem path on demand. MediaService computes only objective facts and stores no creative state; it is the single place that knows where bytes live on disk. Transcription is explicitly out of scope this phase — it arrives in Phase 3.

**Composition (hand-written, single `full` Scene).** Because the Builder and Agent do not exist until later phases, this phase constructs the Composition directly from the Phase 1 types. The Composition declares one **Asset** (the host recording, type `video`), one **voiceover** that points at that same recording's audio (the master clock that sets the composition's duration), and exactly one **Scene** using the `full` **Layout**, whose single `full` **Region** is filled by a **Reference** to the host Asset. There are no overlays, no captions, no transitions. This is the canonical "full host" cut described in the glossary.

**compile_ir (media kind only).** We implement a minimal slice of `compile_ir` that walks the Composition and emits a neutral IR containing a single `media` **Layer** for the host video spanning the full timeline, plus the **voiceover** as an `audio` Layer. Per ADR 0002 the IR is backend-agnostic: it carries timed layers of primitives (media reference, spatial placement, timing, z) and nothing Remotion-specific. This phase exercises only the `media` and `audio` Layer kinds; the `text` kind and keyframe animation tracks are defined by the Phase 1 types but are not produced until Phase 3.

**Remotion `project/` (Node app).** We build the Remotion Node application that receives the IR as `--props` JSON and renders it. For this phase the project understands two of the three Layer kinds — `media` and `audio` — mounting the host video as a full-frame media layer and muxing the voiceover audio onto the output. The project includes the keyframe sampler that reads a Layer's animated tracks and evaluates them per frame; in this phase every track is constant, so the sampler is exercised on its trivial (no-keyframe) path, proving the plumbing before Phase 3 feeds it real animation.

**RemotionBackend (Python subprocess wrapper).** Per ADR 0002, RemotionBackend is a Python class that shells out to the Node/Remotion CLI. It implements both methods of the backend protocol: `render_video` (drives `npx remotion render`, passing the IR JSON as props, returning an mp4 path) and `render_still` (drives the Remotion still command at a given time `t`, returning a single frame image). Both are implemented in this phase because the authoring loop in later phases depends on a cheap `render_still`, and proving it now is nearly free once `render_video` works.

The deliverable is an mp4 of the talking head: a host recording in, a 9:16 mp4 out whose duration matches the recording and whose sampled frames are non-black.

## User Stories

1. As a creator/host, I want to hand the system a single recording of myself talking and get back a playable mp4, so that I can confirm the tool can ingest and re-emit my footage before I trust it with edits.
2. As a creator/host, I want the output mp4's duration to match my recording's duration, so that I know nothing was silently truncated or padded.
3. As a creator/host, I want the host audio preserved as the **voiceover** in the output, so that my speech plays through intact and stays the master clock for everything layered on later.
4. As a creator/host, I want the output to be vertical 9:16, so that it is ready for short-form platforms without further reformatting.
5. As a backend engineer, I want a neutral render **IR** that compiles from a Composition without any Remotion-specific knowledge, so that a future backend swap is a single new interpreter rather than a rewrite of every plugin (ADR 0002).
6. As a backend engineer, I want the IR to carry the host video as a `media` **Layer** and the voiceover as an `audio` **Layer**, so that the simplest case exercises the layer-kind dispatch the full system relies on.
7. As a backend engineer, I want `RemotionBackend.render_video` to accept the IR as `--props` JSON and return an mp4, so that the Python↔Node process boundary is proven on a real render.
8. As a backend engineer, I want `RemotionBackend.render_still` to return a single frame at time `t`, so that the cheap in-loop vision channel the authoring agent will need in later phases is already known to work.
9. As a backend engineer, I want the Remotion `project/` to interpret the IR's Layer kinds rather than per-overlay-type code, so that the backend stays the only place Remotion code lives (ADR 0002).
10. As a backend engineer, I want the keyframe sampler present and exercised on its constant (no-keyframe) path, so that Phase 3's caption animations plug into already-validated machinery.
11. As a backend engineer, I want a clear contract for how seconds in the IR map to Remotion frames given the recording's frame rate, so that timing does not drift across the language boundary.
12. As a media-service developer, I want to ingest a host recording and assign it a stable **Asset** id, so that the rest of the pipeline refers to media by id and never by raw path (ADR 0003).
13. As a media-service developer, I want to probe a recording with `ffprobe` and return duration, dimensions, and frame rate, so that the Composition and IR can be built against objective facts.
14. As a media-service developer, I want to resolve an Asset id to a filesystem path on demand, so that the backend can read the actual bytes at render time while the contract stays id-based.
15. As a media-service developer, I want MediaService to compute only objective facts and hold no creative state, so that the service boundary stays clean and all creative decisions remain elsewhere (ADR 0003).
16. As a media-service developer, I want filesystem paths to be the storage mechanism for v1 with a single seam where outputs are written, so that S3 can be introduced later without touching callers.
17. As a platform maintainer, I want a hand-written single-Scene Composition fixture that round-trips through the Phase 1 types, so that the render path can be tested before the Builder or Agent exist.
18. As a platform maintainer, I want the simplest possible Composition — one Asset, one voiceover, one `full` Scene, no overlays or captions — so that any render failure is unambiguous and localizable to the seam under test.
19. As a platform maintainer, I want an integration test that renders the fixture Composition to an mp4 and asserts the file exists, its duration is approximately the host length, and a sampled frame is non-black, so that the seam is verified by external behavior rather than by inspecting internals.
20. As a platform maintainer, I want a snapshot test of the host-only Composition compiling to the expected IR JSON, so that regressions in `compile_ir` are caught before they reach the backend.
21. As a platform maintainer, I want the Node dependency installation and the `ffmpeg`/`ffprobe` PATH requirement documented as part of the render path, so that a fresh checkout can produce a render.
22. As a platform maintainer, I want the backend exposed behind a protocol with `render_video` and `render_still`, so that a second backend can be slotted in later without changing callers (ADR 0002).
23. As an authoring agent (future consumer), I want `render_still` to already work at this phase, so that when my loop is built I can see my work cheaply without a full render.
24. As a backend engineer, I want the voiceover to define the composition's duration in the IR, so that the master-clock rule from ADR 0005 is honored from the very first render.
25. As a creator/host, I want a render of just my talking head to look correct (right footage, full frame, audio in sync), so that I have confidence in the core before captions and effects are added.

## Implementation Decisions

**MediaService (minimal, facts-only — ADR 0003).** MediaService is implemented as a Python interface with an in-process implementation for v1. Its surface this phase is `ingest` (register a host recording, returning a stable Asset id), `probe` (run `ffprobe` via subprocess and return objective facts), and `resolve` (Asset id → filesystem path). Probe results are objective facts only: duration in seconds, pixel width and height, and frame rate. The service stores no creative interpretation of the media. Path resolution goes through the blob seam so that filesystem paths are the v1 mechanism and an S3 implementation can replace it later without changing callers. `transcribe` is named in the service shape but is not implemented until Phase 3.

**Composition shape (single `full` Scene — ADR 0001, ADR 0005).** The Composition is constructed directly from the Phase 1 kernel types, not via the Builder (which does not exist yet). It contains: a top-level Asset library with one entry (the host recording, type `video`); a **voiceover** that references that recording's audio and is the master clock setting composition duration; and a `scenes` array with exactly one Scene whose Layout is `full` and whose single `full` Region is filled by a Reference to the host Asset with no in-point. The `overlays`, `captions`, and `transitions` collections are empty. This is the declarative model of ADR 0001 reduced to its smallest valid instance: one base-layer Scene, nothing on top.

**compile_ir (media + audio kinds — ADR 0002).** A minimal slice of `compile_ir` walks the Composition and emits the neutral IR. For the single `full` Scene it emits one `media` Layer referencing the host Asset, placed full-frame, spanning `start=0` to the voiceover duration. It emits the voiceover as one `audio` Layer spanning the same range. No `text` Layers are produced (no captions this phase). The compiler resolves Asset references to ids in the IR; the backend resolves ids to paths at render time via MediaService, keeping the IR free of machine-specific paths where practical for the fixture. The IR carries the composition duration derived from the voiceover, honoring ADR 0005's master-clock rule.

The IR Layer shape this phase exercises, sketched to fix the decision precisely:

```
Layer (kind = "media"):
  kind: "media"
  asset: <asset id>        # host recording
  start: 0.0               # seconds, absolute timeline
  end: <voiceover duration>
  region: full-frame placement (x, y, w, h covering the 9:16 frame)
  z: <paint order>
  tracks: {}               # no keyframes this phase; constant by absence

Layer (kind = "audio"):
  kind: "audio"
  asset: <asset id>        # voiceover (host audio)
  start: 0.0
  end: <voiceover duration>
```

The `tracks` field is the animated-value mechanism the keyframe sampler reads; in this phase it is empty so the sampler runs its constant path. Phase 3 populates `tracks` for kinetic captions.

**Remotion project/ (Node app, two Layer kinds).** The Remotion project is a Node/Remotion application that accepts the IR as `--props` JSON. It maps each IR `media` Layer to a media component (the host video mounted full-frame) and the `audio` Layer to an audio component muxed onto the output. The project includes the **keyframe sampler**: a per-frame evaluator that reads a Layer's `tracks` and produces the layer's animated values for the current frame. With empty tracks, the sampler returns the constant placement. The project is configured for a 9:16 output at the host's frame rate. Crucially, the project dispatches on the IR's Layer kinds (`media`/`audio`/`text`), never on overlay types — this keeps the only Remotion code in `backends/remotion/` per ADR 0002.

**RemotionBackend (Python subprocess wrapper — ADR 0002).** RemotionBackend implements the render-backend protocol's two methods. `render_video(ir) → mp4 path` serializes the IR to JSON, invokes the Remotion render CLI (`npx remotion render`) with the IR passed as `--props`, and returns the path to the produced mp4 via the blob output writer seam. `render_still(ir, t) → image path` invokes the Remotion still command at time `t` and returns a single frame image. The wrapper owns subprocess invocation, IR-to-props serialization, frame-rate-aware seconds-to-frame mapping, and surfacing subprocess failures as Python errors. The backend is the only component aware of the Node toolchain.

**Backend protocol (seam for future backends — ADR 0002).** The backend protocol declares `render_video` and `render_still`. RemotionBackend is the first and only implementation this phase, but the protocol is honored so that `FfmpegBackend` or a custom engine can be added later as a single new IR interpreter without changing `compile_ir`, the Composition, or any plugin.

**Service wiring.** Services are wired as direct in-process Python calls per ADR 0003's monolith-first stance. There is no queue and no HTTP transport this phase; the render is invoked synchronously through RemotionBackend. The async RenderService (`submit_render → job_id`) is deferred to Phase 7; this phase calls the backend directly to keep the seam under test as small as possible.

## Testing Decisions

A good test here asserts external, observable behavior of the render path, not the internals of the subprocess invocation or the shape of intermediate Python objects. The render-path integration test follows the plan's per-phase render approach: feed the fixture host-only Composition through `compile_ir` and `RemotionBackend.render_video`, then assert that the mp4 file exists, that its duration is approximately the host recording's length (a tolerance, not an exact equality, because container rounding and frame-rate quantization shift the last fraction of a second), and that a frame sampled from the output is non-black. Non-black is the cheapest meaningful proof that real footage reached the frames rather than an empty canvas; it is deliberately a behavioral signal rather than a pixel-perfect comparison, which would be brittle across Remotion and codec versions.

The IR compilation test is a snapshot test in the style the plan establishes: the host-only Composition compiles to an expected IR JSON, captured as a snapshot that later phases extend (host-only → captions → layouts → effects). This catches `compile_ir` regressions at the data layer before they reach the backend, and it documents exactly what the simplest composition is expected to produce. The snapshot asserts the IR contains one `media` Layer and one `audio` Layer spanning the voiceover duration, with no `text` Layers and empty tracks.

MediaService is tested against objective facts: ingesting a known fixture recording and asserting that `probe` returns the expected duration, dimensions, and frame rate, and that `resolve` maps the assigned Asset id back to the on-disk path. These are behavioral assertions about the facts the service promises (ADR 0003), not about how `ffprobe` is invoked.

`render_still` is tested by rendering a still at a chosen `t` and asserting the image exists and is non-black, mirroring the video assertion at a single frame. This proves the in-loop vision channel before any later phase depends on it.

Prior art: the render-path integration test and the IR snapshot test are the patterns the implementation plan's "Testing approach" section prescribes for the render path and IR compilation respectively, and every subsequent phase reuses and extends them rather than introducing new test shapes.

## Out of Scope

- Transcription and captions of any style — these are Phase 3, the MVP milestone.
- Any Layout other than `full`; the `split-h` layout and its `top`/`bottom` regions are Phase 5.
- B-roll, second assets, multiple scenes, and transitions (cut or crossfade) — Phases 5 and beyond.
- Overlays of any type (`zoom`, `pan`, `insert`) and the overlay/plugin registry — Phases 5 and 6.
- The Builder, Validator, and Resolver; the Composition this phase is hand-written, not built programmatically — Phase 4.
- The async RenderService (`submit_render → job_id`, status/progress) and the background worker — Phase 7; this phase calls the backend directly.
- The CompositionStore, snapshot undo/redo, and the append-only journal — Phase 7.
- The authoring Agent, Builder-ops-as-tools, in-loop vision orchestration, and the review sub-agent — Phases 8 and 8b.
- The E2E CLI — Phase 9.
- A second render backend (`FfmpegBackend` or custom); only `RemotionBackend` is built, behind the protocol that allows one later.
- S3 storage; filesystem paths only, behind the single blob seam.
- MediaService enrichments (silence intervals, shot boundaries, image descriptions, salience).
- Populated keyframe `tracks`; the sampler is exercised only on its constant path this phase.

## Further Notes

This phase is intentionally a tracer bullet. Its value is not the feature (a host recording rendered unchanged is not a product) but the proof that the Python↔Remotion↔IR seam is sound on the simplest case, so that every later phase extends a working pipeline instead of debugging the seam and the feature simultaneously.

The keyframe sampler is built now even though nothing animates, because Phase 3's kinetic captions are the first real consumer of animated `tracks` and we want that machinery already in place and exercised. Likewise `render_still` is built now because the authoring loop in Phase 8 depends on it; proving it here is cheap once `render_video` works.

Verification for this phase aligns with the plan's end-to-end checklist up to the render step: `uv sync`, install Node deps in the Remotion project, ensure `ffmpeg`/`ffprobe` are on PATH, then run the phase tests (the IR snapshot and the render integration test) green and render the fixture host clip to confirm a non-black talking-head mp4.

The empty `tracks` and absent `text` Layers in the IR snapshot are themselves a contract: they assert that the simplest composition produces the simplest IR, and the snapshot grows in Phase 3 when captions add `text` Layers and kinetic animation adds populated tracks. The host-only fixture established here becomes the base case that the MVP acceptance test in Phase 3 builds upon.
