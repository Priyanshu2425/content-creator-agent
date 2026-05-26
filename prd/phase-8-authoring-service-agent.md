# PRD — Phase 8: AuthoringService + Agent

## Problem Statement

By the end of Phase 7 the system can hold a Composition, validate it, resolve a timeline, compile it to IR, and render that IR to an mp4 through the Remotion backend as an async job. Everything below the Composition contract works: the kernel exposes Builder ops, the two-tier validator gates `submit_render`, the Resolver produces a per-frame description, and the stores keep the Composition as the source of truth with snapshot undo and an append-only journal. What is still missing is the thing that actually *decides* what the video should be. Today a Composition only exists if a human (or a test fixture) hand-authors it by calling Builder ops directly. There is no automated author that can take a Media Manifest and a brief and turn them into a finished, valid Composition.

The hard part is not "call an LLM and get JSON back." ADR 0004 is explicit that one-shot JSON generation from an LLM is the wrong shape: large language models reliably emit big, invalid Composition documents that are hard to localize and harder to repair, and the failure mode is opaque — a single malformed overlay can poison the whole document with no clear signal about which decision was wrong. We need an author that builds the Composition the same disciplined way a careful editor would: one decision at a time, each checked immediately against the rules, with errors fed straight back so the next decision can correct course. We also need that author to be able to *see* its work — not on every operation (rendering is expensive), but on demand, when it genuinely needs visual confirmation of framing, occlusion, or timing.

Phase 8 builds the AuthoringService and the authoring agent that lives inside it: Builder ops surfaced to Claude as tools, a tool-use loop that assembles structured perception after every operation, and an agent-triggered in-loop vision channel (a still frame and a scene preview) so the agent controls render cost while still grounding its decisions in pixels. This phase deliberately stops short of the full-motion finalization gate, which is Phase 8b's job.

## Solution

We introduce the **AuthoringService** as the host of the authoring agent, in line with ADR 0003: it is the producer of the Composition, it owns the agent loop, and it stays free of render dependencies because the Builder, Validator, and Resolver it drives all live in the shared kernel. The service takes a Media Manifest (produced by MediaService) plus a free-text brief and returns a complete, validated Composition that is ready to be handed to RenderService.

The agent authors **incrementally via Builder ops exposed as Claude tools**, exactly as ADR 0004 prescribes. We wrap each entity-complete Builder operation (`add_scene`, `fill_region`, `add_overlay`, `add_caption`, `add_captions_from_transcript`, and the rest of the kernel CRUD surface) as an Anthropic tool with a JSON schema derived from the Builder's own parameter types. The authoring loop uses the Anthropic SDK in a tool-use loop with `claude-opus-4-7` (or `claude-sonnet` as a cheaper alternative), per the Tech choices table. The agent calls ops **one at a time**; each op is **validated immediately** by the kernel validator; the validation report — including local hard errors and global reported issues such as scene overlap (error) and gaps (warning) — is fed straight back as the tool result. The accumulated effect of these validated operations *is* the declarative Composition. We never ask the model to emit a Composition document directly.

After every operation the loop assembles a **structured perception** packet and returns it to the agent as part of the tool result. Structured perception is the union of:

- the **Media Manifest** — the assets (id, type, source), their probed durations and dimensions, and the transcript with word-level timings — held stable for the session;
- the **current Composition** as it stands after the op;
- the **Resolver textual timeline** — the Resolver's per-instant frame description rendered as text, so the agent can read what fills each region and which overlays and captions are active across the timeline; and
- the **validation report** for the current Composition.

On top of the always-on structured channel, the agent has an **on-demand, in-loop vision** channel, agent-triggered rather than fired on every op so the agent controls render cost (ADR 0004). Two vision tools are exposed:

- **`render_still`** — a single still frame at an absolute timeline second `t`, produced by the backend's fast `render_still`, returned to the agent as an image; and
- **scene preview** — an image strip of one scene (a small set of sampled frames across that scene's span), returned as images, so the agent can judge motion-adjacent concerns like a zoom's framing or a caption's placement without paying for a full render.

These remain *image-based* in this phase. Full-motion judgement — watching the actual mp4 — is explicitly not in this phase; it is the review sub-agent's job in Phase 8b. The loop terminates when the agent signals it is done and the Composition passes the `submit_render` validation gate, at which point AuthoringService returns the finished Composition.

## User Stories

1. As a creator/host, I want to hand the system my recording, my b-roll, and a short brief and get back a finished edit, so that I do not have to learn an editing tool or hand-write a Composition.
2. As a creator/host, I want the agent to use the actual words I said (the transcript) to place captions, so that the captions match my speech and land on time.
3. As a creator/host, I want my recording's audio to remain the master clock for the whole video, so that scene cuts never desync from what I am saying.
4. As a creator/host, I want must-use moments and style notes in my free-text brief to be honored, so that the edit reflects my intent rather than a generic template.
5. As a creator/host, I want the agent to choose sensible scene cuts, layouts, and effects on my behalf, so that I get a polished short without micromanaging every decision.
6. As an authoring agent, I want to perceive a Media Manifest up front — assets, durations, dimensions, and the transcript with word timings — so that I can plan structure against real facts rather than guesses.
7. As an authoring agent, I want each Builder op surfaced as a tool with a precise parameter schema, so that I can author by calling well-typed operations instead of emitting raw JSON.
8. As an authoring agent, I want to call exactly one Builder op per turn, so that each decision is small, localized, and individually checkable.
9. As an authoring agent, I want each operation validated immediately and the validation report returned to me, so that I can correct an invalid decision on my very next turn.
10. As an authoring agent, I want scene overlaps reported to me as errors, so that I never build a Composition where two scenes fight for the base layer at the same instant.
11. As an authoring agent, I want timeline gaps reported to me as warnings, so that I can tell the difference between an intentional black tail and an accidental hole.
12. As an authoring agent, I want region-validity feedback when I target a layout-specific region, so that I do not place an effect on `top`/`bottom` when no scene exposing those regions is active.
13. As an authoring agent, I want caption-alignment feedback, so that I know when a caption's timing drifts from the transcript word timings.
14. As an authoring agent, I want the current Composition returned after every op, so that I always author against the real accumulated document and never a stale mental model.
15. As an authoring agent, I want a Resolver textual timeline after every op, so that I can read what fills each region and which overlays and captions are active at each instant without rendering.
16. As an authoring agent, I want to request a still frame at an arbitrary timeline second, so that I can confirm framing, occlusion, and composition at a moment I am unsure about.
17. As an authoring agent, I want to request a scene preview as an image strip of one scene, so that I can judge how a scene reads across its span without paying for a full render.
18. As an authoring agent, I want vision to be something I trigger, not something that fires on every op, so that I control how much render cost my authoring incurs.
19. As an authoring agent, I want to add captions from the transcript in one operation, so that I can lay down the word-synced caption track without authoring each caption by hand.
20. As an authoring agent, I want to override or restyle individual captions after the bulk add, so that I can promote a key word to `kinetic` or `word-bold` where the brief calls for emphasis.
21. As an authoring agent, I want to add scenes and fill their regions with asset references that carry in-points, so that I can jump-cut one long host recording across several scenes.
22. As an authoring agent, I want to add full-frame b-roll as a `full` scene and floating b-roll as an `insert` overlay, so that I can pick the right b-roll form per shot.
23. As an authoring agent, I want to add transform overlays like `zoom` and `pan` targeting frame regions, so that I can add motion without per-scene geometry.
24. As an authoring agent, I want to set transitions sparsely by the scene they follow, so that I only ever author the non-cut boundaries.
25. As an authoring agent, I want a signal that I am done so the loop can stop, so that I am not forced to keep operating once the Composition is complete and valid.
26. As an authoring agent, I want the loop to refuse to finish while hard validation errors remain, so that I cannot accidentally ship an invalid Composition.
27. As a review sub-agent, I want the authoring agent to hand off a Composition that already passes the `submit_render` gate, so that the full-motion review I run in the next phase starts from a coherent video.
28. As a platform maintainer, I want the AuthoringService to depend only on the kernel and the agent module, not on render internals, so that the service boundary in ADR 0003 stays clean.
29. As a platform maintainer, I want the tool schemas generated from the Builder's own parameter types, so that the tools cannot drift from the operations they wrap.
30. As a platform maintainer, I want every Builder op available to the agent to be backed by an immediate validation step, so that no tool can mutate the Composition without being checked.
31. As a platform maintainer, I want the in-loop vision tools to go through the backend's `render_still` rather than `render_video`, so that the in-loop channel stays cheap and full-motion stays reserved for finalization.
32. As a platform maintainer, I want the model choice (`claude-opus-4-7` vs `claude-sonnet`) to be configurable, so that I can trade authoring quality against cost without touching the loop.
33. As a platform maintainer, I want the authoring loop to bound the number of operations it will run, so that a confused agent cannot loop indefinitely or run away on cost.
34. As a platform maintainer, I want each op and each vision request recorded against the Composition's audit journal, so that I can reconstruct how the agent reached its decisions.
35. As a CLI user, I want the authoring step to be invokable as a service call from the eventual CLI, so that Phase 9 can wire ingest → author → render without reaching into the agent loop's internals.
36. As a CLI user, I want a clear final Composition returned from authoring, so that the render step has exactly one well-formed input.
37. As an authoring agent, I want my prompt to carry the domain vocabulary precisely (Composition, Scene, Overlay, Caption, Voiceover, Region, Layout, Transition), so that my decisions and tool calls use the same language the kernel enforces.
38. As an authoring agent, I want to know the composition's duration is fixed by the voiceover, so that I plan scene spans within the real length of the recording.

## Implementation Decisions

**New module: `services/authoring.py` (AuthoringService).** This is the host for the agent loop and the perception assembly, fulfilling the AuthoringService role in ADR 0003. Its public contract is an interface that accepts a Media Manifest and a free-text brief and returns a finished, validated Composition (or surfaces the terminal validation report if the agent could not reach a valid state within its operation budget). AuthoringService imports the shared kernel (Builder, Validator, Resolver, Composition types) and the `agent/` module; it does not import backend or render internals. Per ADR 0004, the Builder, Validator, and Resolver living in the kernel is what keeps AuthoringService free of render dependencies. The one render-adjacent dependency it holds is a handle to the backend's `render_still` for the in-loop vision tools — used through the RenderService/backend seam, not by reaching into Remotion directly.

**New/extended module: `agent/tools.py` (Builder ops → Claude tool schemas).** Each entity-complete Builder op is exposed as one Anthropic tool. The tool schema is derived from the Builder operation's Pydantic parameter shape so the tool surface cannot drift from the kernel (a maintainer goal above). The tool set covers the CRUD surface from Phase 4 onward: scene creation and region fill, overlay add (transform and additive), caption add and the bulk `add_captions_from_transcript`, transition set, plus the read/perception and vision tools. Two vision tools are distinct from the mutating ops: `render_still(t)` and `scene_preview(scene_id)`. A terminal `finish` tool lets the agent signal completion.

A representative tool-schema sketch (illustrative of the decision, not a literal file):

```
add_scene(layout: "full" | "split-h", start: seconds, end: seconds, ratio?: float) -> validation_report + structured_perception
fill_region(scene_id, region: "full" | "top" | "bottom", asset_id, in?: seconds) -> validation_report + structured_perception
add_overlay(type: "zoom" | "pan" | "insert", start, end, target_region: "full" | "top" | "bottom", params, z?) -> validation_report + structured_perception
add_caption(text, start, end, style: "pill" | "word-bold" | "kinetic", z?) -> validation_report + structured_perception
add_captions_from_transcript(style?: caption_style) -> validation_report + structured_perception
set_transition(after_scene, kind: "crossfade") -> validation_report + structured_perception
render_still(t: seconds) -> image
scene_preview(scene_id) -> image[]   # sampled strip across the scene span
finish() -> terminates the loop after a final gate check
```

**New/extended module: `agent/loop.py` (authoring tool-use loop).** The loop runs the Anthropic SDK tool-use cycle: present tools + system prompt + initial structured perception (Media Manifest, empty Composition, Resolver timeline, validation report); receive a tool call; dispatch it; for a mutating op, apply the corresponding Builder op, run the validator, and return the validation report plus freshly-assembled structured perception as the tool result; for a vision tool, call the backend's `render_still` (single frame or a sampled strip) and return the image(s); for `finish`, run the `submit_render` gate and either terminate (if clean) or return the blocking report so the agent keeps going. The loop calls ops **one at a time** and validates **immediately**, which is the core ADR 0004 commitment; the accumulated effect *is* the declarative Composition (ADR 0001's derived-state model is untouched — the agent authors imperatively but the runtime model stays declarative, the deliberate inversion noted in ADR 0004). The loop carries an operation budget to bound cost and prevent runaway loops.

**Structured perception assembly.** After each op the loop assembles the perception packet: the stable Media Manifest, the current Composition (serialized from the kernel types), the Resolver textual timeline (the Resolver's per-instant frame description rendered to text — the "agent eyes and sanity" use noted in the repo structure), and the validation report from the two-tier validator. This is the always-on channel. Vision (stills, scene previews) is the on-demand channel layered over it.

**New module: `agent/review.py` is reserved for Phase 8b.** Phase 8 does not implement the ReviewAgent; it only ensures the Composition handed off passes the `submit_render` gate so the Phase 8b finalization loop has a coherent starting point.

**New module: `agent/prompts.py`.** Holds the system prompt that carries the domain vocabulary precisely and explains the loop contract to the model: author one op at a time, read the validation report and Resolver timeline after each, use vision sparingly and deliberately, and call `finish` only when the Composition is complete and clean.

**Backend dependency: `render_still`.** ADR 0002 and ADR 0004 require the backend to support a cheap `render_still(t)` distinct from `render_video()`. Phase 8's in-loop vision relies on `render_still`; `render_video` stays reserved for the Phase 8b review gate. The scene preview is implemented as several `render_still` samples across a scene's span.

**Persistence interaction.** Each applied Builder op and each vision request is recorded against the Composition's append-only audit journal in the CompositionStore (Phase 7), so the authoring trajectory is reconstructable; snapshot undo remains available if a future interactive surface needs it.

**Model and SDK.** Anthropic SDK, tool-use loop, default `claude-opus-4-7` with `claude-sonnet` as a configurable cheaper alternative, per the Tech choices table.

## Testing Decisions

A good test here asserts **external behavior of the AuthoringService and the loop**, not the internal token stream or the exact sequence of model turns. The model is non-deterministic, so tests target the contracts around it rather than its prose.

- **Tool dispatch and schema fidelity (kernel-adjacent, deterministic):** assert that every exposed tool maps to a real Builder op and that a tool call with given arguments produces the same Composition mutation as calling the Builder op directly. Because the kernel Builder and Validator were built TDD-first in Phase 4, these tests can lean on that existing prior art: drive the tools with fixed argument payloads and compare the resulting Composition and validation report against the known-good kernel behavior. No live model needed.
- **Perception assembly:** given a fixed Composition state and a fixed Media Manifest, assert the assembled perception packet contains the Manifest, the current Composition, a Resolver textual timeline consistent with the Resolver's own output, and the validation report — and that the report surfaces scene overlap as an error and a gap as a warning, matching the validator's documented behavior.
- **Loop control with a stubbed model:** drive `agent/loop.py` with a scripted/stubbed Anthropic client that emits a fixed sequence of tool calls (including an intentionally invalid op followed by a correction). Assert the loop validates after each op, feeds the error back, lets the agent recover, and refuses to terminate on `finish` while hard errors remain — then terminates once the `submit_render` gate is clean. Assert the operation budget bounds the loop.
- **In-loop vision routing:** assert that `render_still` and `scene_preview` route through the backend's `render_still` (single frame / sampled strip) and never trigger a `render_video`, and that vision fires only when the agent asks — not on every op. A fake backend that counts `render_still` vs `render_video` calls is sufficient.
- **Live smoke (opt-in, gated on `ANTHROPIC_API_KEY`):** a thin end-to-end of the loop against the real model with a tiny Media Manifest and short brief, asserting the loop terminates with a Composition that passes the `submit_render` gate. This is a smoke check, kept separate from the deterministic suite, and is a precursor to the full E2E smoke in Phase 9.

Following the plan's testing approach, IR-compilation snapshot tests and registry completeness tests are owned by their respective phases and are not duplicated here; Phase 8 tests sit above the kernel, at the service and loop boundary.

## Out of Scope

- The full-motion finalization gate — `render_video()` → video-capable review sub-agent → timestamped feedback → re-render/re-review — is Phase 8b. Phase 8 only guarantees the handoff Composition passes the `submit_render` gate.
- The ReviewAgent interface and any video-capable LLM (e.g. Gemini) integration (Phase 8b).
- The end-to-end CLI (`videogen make …`) and in-process service wiring (Phase 9).
- Any new Builder ops, overlay types, layouts, or caption styles beyond what Phases 4–6 already deliver; Phase 8 exposes the existing kernel surface, it does not extend it.
- MediaService enrichments such as silence intervals, shot boundaries, image descriptions, or salience (out of scope for v1 per the plan); perception is the objective Media Manifest only.
- A structured brief schema; the brief is free text (v1 out-of-scope list).
- A script→TTS / zero-footage path; a host recording remains required (ADR 0005).
- S3 storage, a distributed queue or RPC transport, and a human editor UI (v1 out-of-scope list); the service is in-process and monolith-first (ADR 0003).

## Further Notes

- The deliberate inversion in ADR 0004 is the philosophical center of this phase: the *authoring* API is imperative (Builder ops as tools), while the *runtime* model stays declarative and derived (ADR 0001). The agent never touches runtime state; it composes a document.
- Keeping vision agent-triggered rather than per-op is a cost-control decision, not just an ergonomic one. The Resolver textual timeline is intended to satisfy most "what is on screen" questions for free, reserving pixel-level `render_still` and scene-preview calls for genuine framing/occlusion doubts.
- This phase establishes the multi-model seam without yet crossing it: the authoring agent is the text/tool model; Phase 8b adds the distinct video-review model. Keeping `agent/review.py` reserved here makes the Phase 8b amendment to the final-pass a clean addition rather than a refactor.
- The operation budget and the `submit_render` gate together form the loop's two safety rails: one bounds cost, the other bounds correctness. Both should be observable in the audit journal.
