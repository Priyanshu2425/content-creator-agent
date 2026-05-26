# Phase 4 — Builder + Validator + Resolver

## Problem Statement

By the end of Phase 3 the system can render a talking head with word-synced captions, but every Composition that drives that render has to be hand-written as JSON. Hand-authored Compositions are exactly the failure mode the project is built to avoid: they are tedious, easy to get wrong, and impossible for an authoring agent to produce reliably. ADR 0004 commits the project to incremental, validated authoring rather than one-shot JSON generation, on the grounds that LLMs reliably emit large, invalid documents that are hard to localize and repair. None of the machinery that makes that commitment real exists yet.

Three pieces are missing, and they are interdependent:

1. There is no **imperative authoring API**. The Composition is a declarative document (ADR 0001), but nothing lets a caller construct it operation-by-operation. Without a Builder, both the eventual authoring agent and the kernel's own tests must continue to assemble Composition JSON by hand.

2. There is no **Validator**. The coverage rules in CONTEXT.md (scenes may not overlap; gaps are allowed but should be flagged) and the envelope/param two-phase validation described there are written down but unenforced. Nothing distinguishes a structurally illegal Composition from a merely suspicious one, and nothing gates a Composition from being submitted to render.

3. There is no **Resolver**. ADR 0004 specifies that after each Builder operation the agent perceives a textual timeline derived from the current Composition. That timeline is the agent's cheap, always-available "eyes" — the thing it reads before deciding whether to spend a render call on a still or scene preview. It also serves as a human-readable sanity check during development. Today the only way to know what a Composition looks like at a given instant is to render it.

This phase is pure kernel work and, per the Testing approach in the plan, is the first phase built test-first (TDD). It is the hinge of the whole project: once it lands, Compositions are built programmatically through validated operations rather than typed out by hand, which unblocks everything downstream (layouts, effects, and ultimately the agent).

## Solution

Build three kernel modules — Builder, Validator, and Resolver — entirely within the shared kernel so that they carry no render dependencies and can be imported by AuthoringService later without dragging in Remotion or ffmpeg (ADR 0003, ADR 0004).

The **Builder** is an entity-complete CRUD authoring API over the Composition. It exposes operations to create, read, update, and delete the entities defined in CONTEXT.md, with **scenes and captions first** because those are the entities the talking-head core already exercises. Each operation mutates an in-memory Composition and returns the result of validating that mutation. The Builder is deliberately **imperative**, compiling an imperative operation stream down into the **declarative** Composition document. This is the intentional inversion called out in ADR 0004: imperative is the right shape for *authoring* (a builder is natural to drive op-by-op and to validate per-op), even though it is the wrong shape for *runtime state* (which stays derived, per ADR 0001). The Builder also provides `add_captions_from_transcript`, a higher-level operation that turns word-timed transcript output (from MediaService, Phase 3) into a batch of Caption entries on the dedicated `captions` track, mapping word timings down to absolute seconds.

The **Validator** is two-tier, matching CONTEXT.md's coverage rules and the project's distinction between structural illegality and authoring smell:

- **Local validation** produces **hard errors**. These are conditions a Composition must never contain: overlapping scenes (an error per the coverage rules), a Reference into a region the active Layout does not expose, a target region that is not valid while its scene is active, a Caption whose span falls outside the voiceover, an Asset reference that points at no declared Asset, and overlay-envelope violations. Local errors are surfaced immediately after the operation that introduced them so the loop is self-correcting (ADR 0004).
- **Global validation** produces **reported warnings**. These are conditions that are legal but suspicious — most importantly a **gap** between scenes, which CONTEXT.md says renders as black and must raise a warning (to catch accidental gaps) rather than an error. Warnings never block an operation.

The Validator also defines the **submit_render gate**: a Composition with any outstanding local error cannot be submitted to render. Warnings are informational and do not gate. The gate is a kernel-level predicate so that RenderService (Phase 7) and the eventual agent can consult the same rule.

The **Resolver** answers `(composition, t) → frame description`: given a Composition and an absolute time in seconds, it reports which Scene owns the base layer at `t`, which Layout that Scene uses and what fills each Region, which overlays and captions are active, and their paint order. From this it can render a **textual timeline** across the whole Composition. The Resolver derives state per the ADR 0001 model — it reads the declarative document at `t`, never replays an action stream — so it is total and order-independent. The textual timeline is the agent's primary in-loop perception channel and a development sanity check.

All three modules operate on the Pydantic Composition types built in Phase 1; this phase adds behavior, not new contract types. After this phase, Compositions in tests and in the eventual agent are built programmatically through the Builder, validated by the Validator, and inspected through the Resolver.

## User Stories

1. As a kernel developer, I want a Builder operation that adds a Scene with a chosen Layout and a stable id, so that I can construct the base layer of a Composition programmatically instead of writing JSON.

2. As a kernel developer, I want a Builder operation that fills a Region of a Scene with a Reference to an Asset (optionally with an in-point), so that I can place the host recording or a b-roll Asset into a region without hand-editing the document.

3. As a kernel developer, I want a Builder operation that adds a single Caption with text, start, end, and a caption style to the dedicated captions track, so that I can author caption cues one at a time.

4. As an authoring agent, I want `add_captions_from_transcript` to take MediaService word timings and emit a batch of Captions in absolute seconds, so that I can lay down a full word-synced caption track in one operation rather than calling add-caption per word.

5. As a kernel developer, I want every Builder operation to return the validation result of the mutation it just made, so that I never have to call the Validator separately to learn whether an operation was legal.

6. As an authoring agent, I want each operation validated immediately with localized errors, so that the authoring loop is self-correcting and I can repair a single bad operation instead of re-emitting the whole document (ADR 0004).

7. As a kernel developer, I want read operations that return the current state of any entity in the Composition, so that I can inspect what has been built so far without serializing and re-parsing the document.

8. As a kernel developer, I want update operations on Scenes and Captions (retime, restyle, re-fill a Region), so that I can adjust an existing entity in place rather than deleting and re-adding it.

9. As a kernel developer, I want delete operations on Scenes and Captions, so that the Builder is entity-complete (full CRUD) and an editing session can undo a choice.

10. As an authoring agent, I want the Builder to compile my imperative operation stream into the declarative Composition document, so that I get the ergonomics of step-by-step authoring while the runtime model stays declarative and derivable (ADR 0004, ADR 0001).

11. As a creator/host, I want my recorded talking head to be expressible as a single full-frame Scene filled with my host recording, so that the simplest possible video is the simplest possible authoring path.

12. As a kernel developer, I want the local Validator to reject overlapping Scenes as a hard error, so that the base layer always has at most one Scene owning the frame at any instant (coverage rules, ADR 0001).

13. As a kernel developer, I want the local Validator to reject a Reference that fills a Region the Scene's Layout does not expose, so that region-validity is enforced at authoring time rather than discovered at render.

14. As a kernel developer, I want the local Validator to reject a Caption whose span falls outside the voiceover-defined duration, so that captions cannot point at time that does not exist.

15. As a kernel developer, I want the local Validator to check caption alignment against the timeline (start before end, within bounds, on the captions track), so that malformed cues are caught before render.

16. As a kernel developer, I want the local Validator to reject a Reference to an Asset id that is not declared in the Asset library, so that dangling references are impossible to submit.

17. As a plugin author, I want the envelope of an overlay validated by the fixed core schema separately from its type-specific params, so that the two-phase validation described in CONTEXT.md is honored once overlays arrive in later phases.

18. As a kernel developer, I want a gap between Scenes to raise a global *warning* rather than an error, so that intentional black tails and deliberate gaps are allowed while accidental ones are still surfaced (coverage rules).

19. As a creator/host, I want a trailing gap after my last Scene to be allowed as a black tail, so that the voiceover can keep playing past the final visual cut without the Composition being rejected.

20. As a kernel developer, I want the Validator to clearly separate local hard errors from global reported warnings in its result, so that callers can treat the two tiers differently.

21. As a platform maintainer, I want a single kernel-level `submit_render` gate predicate that blocks a Composition with any outstanding local error, so that RenderService and the agent enforce exactly the same rule.

22. As a platform maintainer, I want warnings to be non-blocking at the submit gate, so that a Composition with a deliberate gap can still be rendered.

23. As an authoring agent, I want the Resolver to tell me which Scene owns the base layer at a given time, which Layout it uses, and what fills each Region, so that I know what is on screen at that instant without rendering.

24. As an authoring agent, I want the Resolver to list the overlays and captions active at a given time together with their paint order, so that I can reason about occlusion and stacking before spending a render call.

25. As an authoring agent, I want the Resolver to emit a textual timeline for the whole Composition, so that I have a cheap, always-available perception channel and only escalate to a still or scene preview when the text is ambiguous (ADR 0004).

26. As a kernel developer, I want the Resolver to derive frame state purely from the declarative document at `t` rather than replaying operations, so that resolution is total and order-independent (ADR 0001).

27. As a kernel developer, I want the Resolver to report a gap at `t` as black (no Scene on the base layer), so that the textual timeline reflects exactly what the renderer will produce.

28. As a creator/host, I want the textual timeline to read naturally enough that a human can sanity-check the edit, so that I can review the structure of my video without watching a render.

29. As a kernel developer, I want all three modules to live in the shared kernel with no render dependencies, so that AuthoringService can import them later without pulling in Remotion or ffmpeg (ADR 0003, ADR 0004).

30. As a platform maintainer, I want the Builder, Validator, and Resolver to operate on the Phase 1 Pydantic Composition types without introducing new contract types, so that this phase adds behavior, not surface area.

31. As an authoring agent, I want a failed operation to leave the Composition unchanged, so that I can retry after a hard error without having corrupted the in-progress document.

32. As a kernel developer, I want `add_captions_from_transcript` to map word-level timings into the canonical absolute-seconds timeline, so that the captions track stays consistent with the rest of the timeline regardless of the transcript's native representation.

33. As an authoring agent, I want to be able to re-run validation on demand over the whole Composition (not just the last mutation), so that I can confirm the document is gate-clean before I submit a render.

34. As a platform maintainer, I want the Validator's local and global tiers to be independently runnable, so that the submit gate (local only) and the perception report (local + global) can request exactly what each needs.

35. As a kernel developer, I want the Builder to assign or accept stable Scene ids that transitions can later key off, so that Phase 5 transitions can reference scenes without temporal coupling (ADR 0001).

## Implementation Decisions

This phase builds three modules in the shared kernel — `builder`, `validator`, and `resolver` — plus whatever small helpers the Resolver needs to format a timeline. It modifies none of the Phase 1 contract types; it consumes them. All three are pure kernel and carry zero render dependencies, per ADR 0003 and ADR 0004, so that AuthoringService can later host them without importing a backend.

**Builder — imperative authoring API over a declarative document.** The Builder wraps an in-memory Composition and exposes entity-complete CRUD operations. The minimum operation set for this phase, with scenes and captions first, is:

- `add_scene(layout, *, id?) → result` — appends a Scene to the ordered base layer with the named Layout and a stable id (assigned if not supplied).
- `fill_region(scene_id, region, asset_id, *, in?) → result` — places a Reference to an Asset into a named Region of a Scene, with an optional in-point (`in`, the source-time offset).
- `add_caption(text, start, end, style) → result` — appends one Caption to the dedicated captions track.
- `add_captions_from_transcript(transcript, *, style) → result` — batch-creates Captions from word-timed transcript output, mapping word timings to absolute seconds.
- read / update / delete counterparts for Scene and Caption (retime, restyle, re-fill, remove) to make the API entity-complete.

Each operation applies the mutation, runs validation, and returns a validation result. Per ADR 0004 the loop is self-correcting: a hard error is fed back and the operation leaves the Composition unchanged (transactional per-op). The Builder is explicitly the imperative front end that compiles into the declarative Composition; this inversion is sanctioned by ADR 0004 and is the only place imperative authoring is allowed — runtime state stays derived (ADR 0001).

An operation result is shaped roughly as:

```
OpResult = { ok: bool, errors: [LocalError], warnings: [GlobalWarning] }
LocalError   = { code, message, entity_ref }   # blocks; localized to the offending entity
GlobalWarning = { code, message, span? }        # reported; never blocks
```

**Validator — two-tier (local hard / global reported), with the submit gate.** The Validator exposes a local pass and a global pass that can run independently, plus a composed full pass. The two-phase envelope/param validation from CONTEXT.md applies to overlays: the type-agnostic Envelope is checked against the fixed core schema, and type-specific params are checked against `registry[type]` — though overlay *types* themselves do not arrive until later phases, so this phase wires the seam and exercises it on the envelope.

Local pass (hard errors): scene non-overlap on the base layer; region-validity (a filled Region must be exposed by the Scene's Layout); target-region validity for any region target; Asset-reference resolvability against the Asset library; Caption alignment (start < end, within voiceover bounds, on the captions track). Global pass (reported warnings): inter-scene and trailing **gaps** raise warnings, never errors, per the coverage rules; the voiceover sets duration and a trailing gap is a legal black tail.

The submit gate is a kernel predicate, `can_submit_render(composition) → bool`, true iff the local pass yields no errors; warnings are ignored by the gate. This same predicate is the one RenderService (Phase 7) and the agent (Phase 8) will consult, so the rule lives in exactly one place (ADR 0003).

**Resolver — `(composition, t) → frame description`, and a whole-timeline view.** The Resolver computes, for an absolute time `t`: the Scene covering `t` (or "black / gap" if none), its Layout and the Reference filling each Region, the active overlays and active Captions, and the paint (`z`) order among additive things. It derives this state by reading the declarative document at `t` (ADR 0001) — never by replaying operations — so resolution is total and seek-cheap. A `timeline(composition) → str` view renders the per-instant description across the Composition as a human- and agent-readable textual timeline; this is the in-loop perception channel ADR 0004 specifies, distinct from (and cheaper than) the still-frame and scene-preview vision channels.

Interactions: the Builder calls the Validator after each op; the agent (later) calls the Resolver after each op to perceive; RenderService and the agent both call the submit gate. Stable Scene ids assigned by the Builder are what Phase 5 transitions will key off (`afterScene: <id>`), and the spatial region targets validated here are the ones Phase 6 effects will use — both deliberately decoupled from index/time to avoid replay-style fragility (ADR 0001).

## Testing Decisions

Per the Testing approach, the kernel is built TDD starting at this phase: tests are written first and drive the Builder, Validator, and Resolver into existence. A good test here asserts **external behavior**, not implementation — it constructs a Composition through Builder operations and asserts on the observable result (the operation's validation outcome, the Validator's error/warning sets, the Resolver's frame description or timeline text), never on private internals.

Builder tests: drive a sequence of operations and assert the resulting Composition (round-tripped through the Phase 1 types) is what was intended; assert that an illegal operation returns a hard error and leaves the document unchanged (transactional behavior); assert `add_captions_from_transcript` produces caption spans in absolute seconds matching the input word timings.

Validator tests, organized by the explicit cases the plan names: overlapping scenes produce an error; a gap produces a warning and not an error; a Reference into a Region the Layout does not expose produces an error; a Caption outside voiceover bounds or with start ≥ end produces an error (caption alignment); a dangling Asset reference produces an error; a trailing gap is allowed (warning only). Crucially, assert the **tier**: the same gap that warns must not block the submit gate, and any local error must block it.

Resolver tests: at a chosen `t`, assert the reported Scene, Layout, Region fills, active overlays/captions, and paint order; assert a `t` inside a gap resolves to black with no base Scene; assert the textual timeline covers the whole Composition and reflects gaps. Because the Resolver derives state declaratively, tests should confirm order-independence — building the same Composition via different operation orders yields the same resolution at the same `t`.

Prior art: this is the foundation the plan's later test layers build on. The IR-compilation snapshot tests (Phase 5 onward) will feed on Compositions produced by this Builder, and the render-path integration tests will submit only gate-clean Compositions. Keeping these kernel tests behavior-level means later phases can refactor module internals without breaking them.

## Out of Scope

- Overlay *types* and their param schemas (`zoom`, `pan`, `insert`) — Phase 6. This phase only wires the two-phase envelope/param validation seam and exercises the envelope.
- Layout plugins and the plugin Registry / completeness check — Phase 5. This phase validates region-validity against whatever Layouts the Phase 1 types expose; it does not build the registry.
- Transitions (cut default, crossfade) — Phase 5. Scene ids are made stable here so transitions can key off them later, but no transition entity is authored.
- IR compilation — the Builder/Validator/Resolver operate on the Composition only; `compile_ir` is not driven from this phase.
- Persistence: snapshot undo/redo and the append-only audit journal — Phase 7. The Builder mutates an in-memory Composition; durable history is not this phase's concern.
- The authoring agent, Builder-ops-as-Claude-tools, and the still/scene-preview vision channels — Phase 8. The Resolver's textual timeline is built here as the cheap perception channel, but the agent that consumes it is not.
- The review sub-agent and finalization loop — Phase 8b.
- Any render output, backend interaction, or `render_still`/`render_video` — out of this phase entirely.

## Further Notes

This phase is the inflection point the build order is organized around: the comment in the plan, "Composition now built programmatically, not hand-written," is the acceptance summary. Once Builder, Validator, and Resolver land, no later phase and no test should be assembling Composition JSON by hand.

The deliberate imperative-over-declarative inversion (ADR 0004) is worth stating plainly in code-review terms: the Builder is allowed to be imperative precisely because its output is a declarative document that is re-derivable; it is not a replay log. The Resolver is the guardrail that keeps this honest — if frame state can always be derived from the document at `t`, the document is genuinely declarative regardless of how it was built.

The two-tier Validator's hardest design judgement is the error/warning boundary, and CONTEXT.md fixes the one case that most invites debate: a gap is a warning, not an error, because gaps are legal (they render as black with the voiceover continuing) but are also a common accident. Encoding that exact distinction — and proving via test that a gap does not trip the submit gate — is the load-bearing behavior of this phase.

The Resolver's textual timeline is intentionally the agent's *first* and cheapest sense. Keeping it expressive enough to answer "what is on screen at t" without a render is what lets ADR 0004's cost-controlled, agent-triggered vision model work later: the agent reads the timeline for free and only pays for a still or scene preview when the text leaves it uncertain.
