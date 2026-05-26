# Phase 3 — Transcription → Captions ⇒ MVP

## Problem Statement

Phase 2 proved the Python↔Remotion↔IR seam on the simplest case: a host recording rendered straight through to an mp4 with its **voiceover** intact. That output, while a real render, is not yet a product — it is the host's raw footage re-emitted. The genre this system targets is the talking-head short: a speaker on screen with their own words appearing as word-synced, styled **captions**. Until those captions exist and land on time over the speaker, there is nothing here a creator would publish.

This phase closes that gap and is the **MVP milestone**. It requires two new capabilities. First, MediaService must transcribe the host recording's audio into word-level timings — not sentence-level subtitles, but per-word start/end times, because the three caption styles we ship depend on word granularity (a single emphasis word, a pop-in key word, a rolling pill of speech). Second, those timed words must compile into the neutral IR as `text` **Layers**, including the animated case where a kinetic caption pops in via opacity and scale keyframes — the first real exercise of the IR's animation vocabulary and the keyframe sampler that Phase 2 built but left on its constant path.

The bar for this phase is concrete and externally observable: take a real host clip, transcribe it, and render an mp4 in which the spoken words appear as captions that are on time and correctly styled in each of the three styles — `pill`, `word_bold`, and `kinetic`. Hitting that bar means the core talking-head experience works end to end, and every later phase (layouts, b-roll, effects, the Agent) becomes an additive layer on a shipping core rather than a prerequisite for a first usable output.

## Solution

We add transcription to MediaService, define the three caption styles, compile **Captions** into IR `text` Layers (with keyframe animation for `kinetic`), and render the result — delivering the MVP: a talking head with word-synced captions as an mp4.

**Transcription (MediaService, word timings — ADR 0005).** We implement `MediaService.transcribe` using `faster-whisper` with `word_timestamps=True`. It always targets the host recording's audio, consistent with ADR 0005 — the host audio is the voiceover and the transcript is what captions hang off. The output is a transcript carrying per-word text and word-level start/end times in seconds, since the **Timeline** keeps seconds canonical (word-timings compile down to seconds). Transcription remains an objective fact MediaService produces (ADR 0003); it makes no creative decision about how words are grouped into captions or which style each takes.

**Caption styles (`pill` / `word_bold` / `kinetic`).** We define the three known caption styles from the glossary as presets: `pill` (dark rounded background for normal speech), `word_bold` (plain white emphasis word), and `kinetic` (large pop-in for a key word). A **caption style** is a named preset controlling a caption's appearance; the Caption itself carries `text`, `start`/`end`, and its style. Captions live on the dedicated `captions` track, kept off the overlays list because they are voluminous and homogeneous.

**Captions → IR `text` Layers.** We extend `compile_ir` to compile each Caption into an IR `text` Layer: a text run plus the style's visual properties, placed and timed on the absolute-seconds timeline, with a `z` chosen so captions paint above the host media (high `z` by convention, since captions are additive and must stay on top). For `pill` and `word_bold` the text Layer is constant within its span. For `kinetic`, the text Layer carries opacity and scale **keyframe** tracks that drive the pop-in — the first populated animation tracks in the system, evaluated per frame by the keyframe sampler from Phase 2.

**Render the MVP.** With `text` Layers (animated and constant) added to the IR alongside the Phase 2 `media` and `audio` Layers, the existing Remotion `project/` and `RemotionBackend.render_video` produce the MVP mp4: the talking head with word-synced captions. The Remotion project gains a `text`-kind component (and uses the keyframe sampler for kinetic animation), but the dispatch stays on IR Layer kinds, not per-caption-style code in the backend — style differences are encoded in the IR the compiler emits.

The deliverable is the MVP milestone: a real host clip → mp4 with on-time, correctly-styled captions in the three styles.

## User Stories

1. As a creator/host, I want my spoken words to appear as captions on the video, so that my short is watchable with sound off and feels like the talking-head genre I am making.
2. As a creator/host, I want captions to appear and disappear in sync with what I actually said, so that the words on screen match my speech.
3. As a creator/host, I want word-level timing accuracy, so that emphasis and pop-in captions land on the exact word rather than a whole sentence.
4. As a creator/host, I want a `pill` style for normal speech, so that ordinary narration reads cleanly on a dark rounded background.
5. As a creator/host, I want a `word_bold` style for an emphasis word, so that a single word can be called out in plain white.
6. As a creator/host, I want a `kinetic` style for a key word, so that an important word pops in large to grab attention.
7. As a creator/host, I want captions to sit on top of my face without my footage covering them, so that the text is always legible.
8. As a creator/host, I want the captions rendered over the same talking-head footage from the host-only path, so that the MVP is the core experience and nothing else.
9. As a creator/host, I want my voiceover to keep playing straight through as the master clock, so that captions are pinned to real speech time and never drift (ADR 0005).
10. As a media-service developer, I want `transcribe` to run `faster-whisper` with `word_timestamps=True` against the host audio, so that I produce per-word start/end times for captioning (ADR 0005).
11. As a media-service developer, I want transcription to always target the host recording's audio, so that the transcript is anchored to the voiceover and the master clock (ADR 0005).
12. As a media-service developer, I want word timings expressed in seconds, so that they slot directly onto the absolute-seconds Timeline without unit conversion downstream.
13. As a media-service developer, I want transcription to remain an objective fact with no grouping or styling decisions, so that creative choices stay out of MediaService (ADR 0003).
14. As a media-service developer, I want the transcript surfaced as part of the Media Manifest, so that a later authoring Agent can perceive word timings when it builds captions.
15. As a backend engineer, I want each Caption to compile to an IR `text` Layer, so that the backend interprets Layer kinds rather than caption styles (ADR 0002).
16. As a backend engineer, I want caption styles encoded as visual properties in the IR `text` Layer, so that style differences live in the compiled data and the backend stays free of per-style branching.
17. As a backend engineer, I want a `kinetic` caption to compile to opacity and scale keyframe tracks on its `text` Layer, so that the pop-in animation is expressed in the IR's animation vocabulary (ADR 0002).
18. As a backend engineer, I want the keyframe sampler from Phase 2 to evaluate those tracks per frame, so that the constant path proven earlier now drives real animation.
19. As a backend engineer, I want captions assigned a high `z` so they paint above the host media, so that additive caption layers stay on top of the base media layer.
20. As a backend engineer, I want the Remotion `project/` to gain a `text`-kind component without changing how it dispatches, so that the backend continues to interpret only the three IR Layer kinds (ADR 0002).
21. As a backend engineer, I want `render_video` to emit the captioned mp4 with no change to its contract, so that adding captions is a compile-time and backend-component change, not a render-API change.
22. As a platform maintainer, I want a host-plus-captions Composition fixture that extends the Phase 2 host-only fixture, so that the MVP is tested against the established base case.
23. As a platform maintainer, I want the IR snapshot test extended from host-only to captions, so that caption compilation regressions are caught at the data layer before reaching the backend.
24. As a platform maintainer, I want the IR snapshot to show `text` Layers for `pill`/`word_bold`/`kinetic`, with the kinetic one carrying opacity and scale keyframe tracks, so that the compiled shape of each style is documented and pinned.
25. As a platform maintainer, I want an MVP acceptance test that takes a real host clip and renders an mp4 with on-time, correctly-styled captions in the three styles, so that the milestone is verified by external behavior.
26. As a platform maintainer, I want the MVP acceptance test to assert captions appear at the expected times, so that word-sync is checked rather than just the presence of text.
27. As a platform maintainer, I want transcription tested against a known clip's expected words and approximate timings, so that the facts MediaService promises are verified behaviorally (ADR 0003).
28. As an authoring agent (future consumer), I want word timings in the Manifest, so that when my loop exists I can place captions on the right words.
29. As an authoring agent (future consumer), I want the three caption styles available as presets, so that I can choose a style per caption without inventing one.
30. As a backend engineer, I want captions kept off the overlays list and on the dedicated `captions` track, so that the voluminous, homogeneous caption data does not bloat the overlay union (ADR 0001).
31. As a creator/host, I want the MVP mp4 to be 9:16 with audio in sync and captions on time, so that it is a publishable short-form video, not a demo artifact.

## Implementation Decisions

**MediaService.transcribe (faster-whisper, word timings — ADR 0005, ADR 0003).** We implement the `transcribe` method on MediaService using `faster-whisper` configured with `word_timestamps=True`. It resolves the host Asset to a path, runs transcription on that audio, and returns a transcript of per-word entries, each carrying the word text and its start/end time in seconds. Per ADR 0005 it always targets the host recording's audio (the voiceover). Per ADR 0003 the result is an objective fact: MediaService does not group words into captions, choose styles, or make any creative decision. The transcript becomes part of the Media Manifest that the authoring Agent will later perceive. WhisperX is noted as a higher-accuracy alternative but is not adopted in this phase.

**Caption model and styles (ADR 0001).** Captions are carried on the Composition's dedicated `captions` track, deliberately separate from the `overlays` union because captions are voluminous and homogeneous. Each Caption carries `text`, `start`/`end` in seconds, and a **caption style**. The three styles are defined as named presets: `pill`, `word_bold`, and `kinetic`. The style is a presentation preset only; it does not change the Caption's structural fields. Because the Builder does not yet exist (it arrives in Phase 4 with `add_captions_from_transcript`), this phase constructs the captioned Composition directly from kernel types, mapping transcript words onto Captions in the fixture so the render path can be tested.

**compile_ir extension — Captions to `text` Layers (ADR 0002).** `compile_ir` gains caption handling on top of the Phase 2 `media`/`audio` slice. Each Caption compiles to one IR `text` Layer spanning its `start`/`end`, carrying the text run and the style's visual properties (background/shape for `pill`, weight/color for `word_bold`, size and pop-in for `kinetic`), and a `z` high enough to paint above the host `media` Layer (captions are additive and must stay on top). For `pill` and `word_bold` the `text` Layer's tracks are empty (constant within span). For `kinetic` the `text` Layer carries animated tracks — opacity rising from transparent to opaque and scale springing up to settle — expressed as keyframes the sampler evaluates per frame. This is the first populated animation in the IR and the first real use of the keyframe vocabulary referenced by ADR 0002.

The IR `text` Layer shapes this phase introduces, sketched to fix the styling and animation decisions precisely:

```
Layer (kind = "text") — pill / word_bold (constant):
  kind: "text"
  text: "<word or phrase>"
  style: "pill" | "word_bold"   # drives compiled visual props
  start, end: seconds
  z: <high; above media>
  tracks: {}                    # constant within span

Layer (kind = "text") — kinetic (animated):
  kind: "text"
  text: "<key word>"
  style: "kinetic"
  start, end: seconds
  z: <high; above media>
  tracks:
    opacity: [ keyframe(t=start, 0.0), keyframe(t=start+pop, 1.0) ]
    scale:   [ keyframe(t=start, small), keyframe(t=start+pop, 1.0) ]
```

The exact easing and pop duration are part of the `kinetic` preset's compiled output; the load-bearing decision is that style and animation are encoded by the compiler into the neutral IR, so the backend never branches on caption style.

**Remotion project/ — `text` component (ADR 0002).** The Remotion project gains a component for the IR `text` Layer kind: it renders the text run with the visual properties carried in the Layer, and for animated layers it reads the opacity and scale tracks through the keyframe sampler from Phase 2 to drive the kinetic pop-in. Dispatch remains on the three IR Layer kinds (`media`/`text`/`audio`); the backend has no knowledge of `pill`/`word_bold`/`kinetic` as such — it only paints the visual props and animates the tracks the compiler emitted. This keeps the only Remotion code in `backends/remotion/` and honors the IR-as-contract boundary of ADR 0002.

**No change to backend contract.** `RemotionBackend.render_video` and `render_still` are unchanged in signature. Adding captions is a `compile_ir` change plus a new `text`-kind component in the Remotion project; the render API and the service wiring (still direct in-process calls, no async RenderService yet) are untouched.

**Master clock preserved (ADR 0005).** Caption `start`/`end` times derive from word timings on the same absolute-seconds Timeline whose master clock is the voiceover. The voiceover continues to set composition duration; captions are pinned to real speech time and cannot drift relative to the audio.

## Testing Decisions

The defining test of this phase is the **MVP acceptance test**, which the implementation plan places at the end of Phase 3: a real host clip is transcribed and rendered to an mp4, and the test asserts the output has on-time, correctly-styled captions in the three styles. This is an external-behavior test — it checks what an actual short-form video should exhibit, not how the compiler is wired. On-time is verified by asserting captions are present at the timeline positions implied by the transcript words (sampling frames at expected caption times and confirming text-bearing, non-background content appears, and confirming frames between captions do not). Correctly-styled is verified by exercising a fixture that uses all three styles and confirming each renders its distinguishing visual characteristic. As in Phase 2, frame assertions stay behavioral (presence and timing) rather than pixel-perfect, which would be brittle across Remotion and codec versions.

The IR compilation snapshot test extends the Phase 2 host-only snapshot to the captions case, as the plan prescribes (host-only → captions → layouts → effects). The snapshot asserts the captioned Composition compiles to the Phase 2 `media` and `audio` Layers plus one `text` Layer per Caption, that `pill` and `word_bold` text Layers have empty tracks, and that the `kinetic` text Layer carries opacity and scale keyframe tracks with the expected keyframe times relative to the caption start. This pins the compiled shape of every style at the data layer and catches caption-compilation regressions before they reach the backend.

MediaService transcription is tested against a known fixture clip: the test asserts that `transcribe` returns the expected words in order with start/end times that fall within a tolerance of the known utterance times. These are behavioral assertions about the objective facts MediaService promises (ADR 0003), tolerant of the small timing variance inherent in speech recognition rather than demanding exact equality.

The render-path integration test from Phase 2 is extended: the captioned fixture Composition renders to an mp4, and the test asserts the file exists, the duration is approximately the host length, and sampled frames are non-black — now additionally checking that frames at caption times carry caption content.

Prior art: this phase reuses the render-path integration pattern and the IR snapshot pattern established in Phase 2 and prescribed in the plan's "Testing approach", extending the snapshot and adding the MVP acceptance test as the milestone gate. The kernel TDD discipline (Builder/Validator/Resolver tests-first) begins in Phase 4; this phase's compile and render are covered by snapshot and integration tests.

## Out of Scope

- The Builder operation `add_captions_from_transcript`; this phase maps transcript words to Captions directly in the fixture, while the programmatic Builder op is Phase 4.
- The two-tier Validator (overlap/gap/region-validity/caption-alignment checks) and the `submit_render` validation gate — Phase 4.
- The Resolver timeline — Phase 4.
- Caption styles beyond the three known presets (`pill`, `word_bold`, `kinetic`); no new style is introduced.
- Choosing which words get which style automatically; style assignment in the fixture is fixed, and intelligent style selection is the Agent's job in Phase 8.
- Layouts other than `full`, `split-h`, b-roll scenes, and transitions — Phase 5.
- Overlays of any type (`zoom`, `pan`, `insert`) and the registry — Phases 5 and 6.
- The async RenderService, CompositionStore, and journal — Phase 7.
- The authoring Agent, in-loop vision, and the review sub-agent — Phases 8 and 8b.
- The E2E CLI — Phase 9.
- WhisperX or any transcription engine other than `faster-whisper`; WhisperX is noted only as a future higher-accuracy alternative.
- Speaker diarization, punctuation refinement, or any transcript post-processing beyond word timings.
- A second render backend; `RemotionBackend` remains the only implementation behind the protocol.
- S3 storage; filesystem paths only, behind the existing blob seam.

## Further Notes

This is the MVP milestone — the point at which the system produces something a creator would actually publish: their talking head with their own words as word-synced, styled captions. Everything in the build order after this (layouts, b-roll, effects, the Agent, the review sub-agent, the CLI) is additive, layered on a working core, which is exactly the talking-head-first sequencing the plan and ADR 0005 commit to.

The `kinetic` style is the first real consumer of the keyframe sampler built in Phase 2. Proving opacity and scale animation here, on a single pop-in word, de-risks the IR animation vocabulary before Phase 6's overlay effects (`zoom`/`pan`) lean on the same keyframe machinery for spatial transforms.

Because captions are pinned to word timings on the voiceover-master-clock Timeline (ADR 0005), the MVP acceptance test's on-time assertion is meaningful: a caption that drifts from its word would be a real failure visible in the rendered frames, not just a unit-level mismatch.

Verification for this phase follows the plan's MVP check: with `uv sync`, the Remotion Node deps installed, and `ffmpeg`/`ffprobe` on PATH, run the phase tests green (extended IR snapshot, transcription facts, extended render integration, MVP acceptance) and render a sample host clip to confirm `renders/<id>.mp4` shows the talking head with word-synced captions in the three styles.
