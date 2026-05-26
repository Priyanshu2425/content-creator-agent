# PRD — Phase 9: End-to-End CLI

## Problem Statement

By the end of Phase 8b every piece of the pipeline exists and works in isolation: MediaService ingests, probes, transcribes, and resolves `id → path`; the kernel holds the Composition, validates it, resolves a timeline, and compiles it to IR; the Remotion backend turns IR into frames; RenderService runs renders as async jobs; the AuthoringService hosts an authoring agent that builds a valid Composition from a Media Manifest and a brief; and a video-capable review sub-agent gates finalization. What does not yet exist is a single entry point that a person can run. The services are wired conceptually but there is no command that takes a creator's raw inputs and produces a finished mp4 by walking the whole pipeline.

ADR 0003 committed us to a monolith-first, service-shaped design: the three services are defined as interfaces and, for v1, wired as direct in-process calls in one deployable, with the transport free to become HTTP + a real queue later without a redesign. ADR 0005 committed us to a talking-head-first kickoff: the user provides a host-cam recording whose audio *is* the master-clock voiceover, plus optional b-roll assets, plus a short free-text brief. Phase 9 is where those two ADRs meet in a runnable command. Until this command exists, the system cannot be exercised end to end, the E2E smoke test cannot run, and the full-verification target — the reference-video shape — cannot be reached.

## Solution

We build `app/cli.py`, exposing a single command:

```
videogen make --host host.mp4 [--broll a.png,b.mp4] --brief "…"
```

- `--host` is **required** — the host-cam recording whose audio is the voiceover and master clock (ADR 0005).
- `--broll` is **optional**, a **comma-separated** list of b-roll assets (movie clips and/or screenshots).
- `--brief` is **free text** — topic, target length, style, must-use moments (no structured brief schema; that is out of scope per the plan).

The command walks the pipeline by calling the three services **in-process, behind their interfaces** (ADR 0003, monolith-first):

1. **Ingest + transcribe (MediaService).** Probe the host recording and each b-roll asset for duration, dimensions, and fps via `ffprobe`; register assets and resolve their filesystem paths; transcribe the host audio with word-level timings via faster-whisper. The objective facts produced here form the **Media Manifest** (assets with types/durations/dimensions, plus the transcript with word timings). MediaService produces facts only — no creative decisions (ADR 0003).
2. **Author (AuthoringService).** Hand the Media Manifest and the free-text brief to the authoring agent (Phase 8), which builds a valid Composition one validated Builder op at a time, then runs the Phase 8b finalization gate (render → video-review → edits → re-render, capped at N rounds).
3. **Submit render (RenderService).** `submit_render` the finalized Composition → `job_id`; the render runs in the background worker (Composition → IR → backend → mp4, ADR 0002/0003); the CLI follows status/progress to completion and reports the output mp4 path.

The deliverable is a working command and the **E2E smoke test**: a host clip + one b-roll + a short brief → an mp4, with the job completing. The full-verification target is the **reference-video shape**: a split-screen hook, the host with a slow zoom, a b-roll cut, and synced captions.

## User Stories

1. As a CLI user, I want a single `videogen make` command, so that I can turn my raw inputs into a finished short without orchestrating the pipeline myself.
2. As a CLI user, I want `--host` to be required, so that the command fails fast and clearly when I forget the recording that anchors the whole video.
3. As a CLI user, I want my host recording's audio to drive the video's timing, so that the result respects what I actually said as the master clock.
4. As a CLI user, I want `--broll` to be optional, so that I can produce a talking-head-only short with no b-roll at all.
5. As a CLI user, I want `--broll` to accept a comma-separated list, so that I can pass several b-roll assets in one flag.
6. As a CLI user, I want to mix b-roll types (a screenshot and a movie clip) in one `--broll` list, so that I am not restricted to a single media kind.
7. As a CLI user, I want `--brief` to be free text, so that I can describe topic, length, style, and must-use moments in plain language without learning a schema.
8. As a CLI user, I want the command to ingest and probe my files before doing anything expensive, so that a bad path or unreadable file is caught early.
9. As a CLI user, I want my host audio transcribed automatically, so that captions and timing decisions come from my real speech without a manual transcript.
10. As a CLI user, I want the agent to author the edit from my Manifest and brief, so that I receive structural and stylistic decisions made for me.
11. As a CLI user, I want the finished video reviewed in motion before I get it, so that the output reflects the finalization gate, not just a first pass.
12. As a CLI user, I want the render to run as a background job, so that a multi-minute render does not appear to hang the command.
13. As a CLI user, I want progress and status reported while the render runs, so that I know the job is advancing rather than stuck.
14. As a CLI user, I want the final mp4's output path printed when the job completes, so that I can find and play my video.
15. As a CLI user, I want a clear error if transcription, authoring, or rendering fails, so that I know which stage broke and why.
16. As a CLI user, I want to run the reference-video example from the plan and get the reference-video shape, so that I can verify the whole system end to end.
17. As a creator/host, I want a one-command path from recording to short, so that the tool fits the talking-head workflow without an editing UI.
18. As a creator/host, I want my must-use moments in the brief honored in the final cut, so that the edit reflects the beats I care about.
19. As a creator/host, I want word-synced captions over my speech in the output, so that the MVP caption experience carries through to the full pipeline.
20. As an authoring agent, I want the CLI to deliver me a complete Media Manifest, so that I author against probed facts and a real transcript rather than raw file paths.
21. As an authoring agent, I want the CLI to pass the free-text brief through untouched, so that I interpret the creator's intent directly.
22. As a review sub-agent, I want the CLI's pipeline to route the finalized render through me before completion, so that no video ships without a full-motion review pass.
23. As a platform maintainer, I want the three services wired as direct in-process calls behind their interfaces, so that the v1 monolith honors ADR 0003 and can later become HTTP + a queue without a redesign.
24. As a platform maintainer, I want the CLI to depend on the service interfaces, not their internals, so that swapping a transport or an implementation later does not touch the command.
25. As a platform maintainer, I want the CLI to be thin — argument parsing and orchestration only — so that all real logic stays in the services and the kernel.
26. As a platform maintainer, I want the E2E smoke test to run a host clip + one b-roll + short brief to a completed mp4, so that the whole wiring is continuously verified.
27. As a platform maintainer, I want the render to go through `submit_render → job_id → status → artifact`, so that the async job contract from ADR 0003 is exercised by the real entry point.
28. As a platform maintainer, I want the CLI to surface the same validation gate the services enforce, so that an invalid Composition can never reach the renderer through the command.
29. As a platform maintainer, I want the full-verification example reproducible from a documented command, so that the reference-video shape is a checkable target rather than a claim.
30. As a CLI user, I want the command to work with `ffmpeg`/`ffprobe` on PATH and `ANTHROPIC_API_KEY` set, so that the prerequisites are explicit and the failure is clear when one is missing.

## Implementation Decisions

**New module: `app/cli.py`.** A thin command-line entry point exposing `videogen make`. Responsibilities: parse `--host` (required), `--broll` (optional, comma-separated), and `--brief` (free text); orchestrate the three services in sequence; follow the render job to completion; print the output mp4 path. The CLI holds no domain logic — all of it lives in the services and the kernel (ADR 0003). It depends on the **service interfaces**, not their concrete internals, so the later transition to HTTP + a real queue is a transport change rather than a CLI rewrite.

**In-process service wiring (ADR 0003, monolith-first).** The CLI constructs and calls MediaService, AuthoringService, and RenderService as direct in-process calls within one deployable. The Composition JSON remains the message contract between them. The async-render benefit is preserved: `submit_render` returns a `job_id` and the render runs in the Phase 7 background worker (`concurrent.futures` ThreadPoolExecutor + in-memory job registry per the Tech choices table); the CLI polls status/progress to completion. Nothing in the CLI assumes same-process-ness in a way that would block the later split.

**Pipeline sequence.** The command realizes the ADR 0003 + ADR 0005 flow:

```
videogen make --host host.mp4 [--broll a.png,b.mp4] --brief "…"
  -> MediaService: ingest + probe (ffprobe) + transcribe (faster-whisper, word_timestamps) + resolve id->path
     => Media Manifest (assets w/ type/duration/dims; transcript w/ word timings)
  -> AuthoringService: authoring agent builds validated Composition (Phase 8)
                       + finalization gate w/ video-review sub-agent (Phase 8b)
  -> RenderService: submit_render(Composition) -> job_id -> status/progress -> mp4 artifact
```

- **MediaService** (`services/media.py`) produces objective facts only (ADR 0003): probe durations/dims/fps, register and resolve asset paths through `blobs.py` (filesystem paths, single render-output writer, S3-later seam), and transcribe the host audio. The host recording's audio is the voiceover and master clock (ADR 0005); transcription always targets it.
- **AuthoringService** (`services/authoring.py`) hosts the Phase 8 authoring loop and the Phase 8b finalization gate, returning the finalized, reviewed Composition.
- **RenderService** (`services/render.py`) compiles the Composition to IR and renders via the Remotion backend (ADR 0002), as an async job.

**Input handling.** `--host` is validated as present and ingestable before any expensive stage; `--broll` is split on commas into individual assets and each is probed/registered; `--brief` is passed through to AuthoringService as opaque free text (no structured brief schema — out of scope per the plan). A missing or unreadable file fails fast at the ingest stage with a clear error.

**Prerequisites surfaced.** Per the Verification section, the command expects `ffmpeg`/`ffprobe` on PATH, Node deps installed in `backends/remotion/project`, and `ANTHROPIC_API_KEY` set (plus the review model's key for the Phase 8b gate). The CLI should fail with a legible message when a prerequisite is missing rather than deep inside a subprocess.

**No new domain capability.** Phase 9 introduces no new Builder ops, overlay types, layouts, caption styles, IR vocabulary, or render features. It is pure wiring and an entry point over the stack built in Phases 0–8b.

## Testing Decisions

The headline test for this phase is the **E2E smoke test** named in the plan's testing approach: a host clip + one b-roll + a short brief → an mp4, with the job completing. This is an external-behavior test of the whole wired pipeline — it asserts the observable outcome (a video file is produced and the render job reaches completion), not how any stage did its work.

- **E2E smoke (the Phase 9 deliverable):** run `videogen make` against a real short host clip, one b-roll asset, and a short brief. Assert the command completes, the render `job_id` reaches a completed status, the output mp4 exists, its duration is approximately the host clip length (voiceover is the master clock), and a sampled frame is non-black. This reuses the per-phase render-integration prior art (file exists / duration ≈ host length / sampled frame non-black) from the plan and extends it across the full pipeline. Because it invokes the real authoring and review models, it is gated on the relevant API keys and kept separate from the fast deterministic suite.
- **Argument parsing and orchestration (deterministic):** with the three services replaced by fakes, assert `--host` is required and rejected when missing; `--broll` is split on commas into the right asset list; `--brief` is passed through to AuthoringService unchanged; the services are invoked in the correct order with the Composition as the contract between them; and the CLI follows `submit_render → job_id → status → artifact` and prints the final path. This tests the CLI's job (parsing + orchestration) without invoking models or rendering.
- **Failure surfacing:** with fakes that raise at each stage in turn (ingest, transcribe, author, render), assert the CLI reports which stage failed with a legible message and a non-zero exit, so a broken file or a failed render is diagnosable.
- **Full verification target (manual / acceptance):** the documented reference-video command (`--host samples/host.mp4 --broll samples/tweet.png --brief "50s short on X; open on the clip; cite the tweet"`) should produce the reference-video shape — a split-screen hook, host with a slow zoom, a b-roll cut, and synced captions. This is the end-of-Phase-9 full check from the Verification section; it is an acceptance target exercised by a human or a tagged acceptance run rather than a unit assertion, because the agent's creative choices are non-deterministic.

Per the plan, kernel unit tests, IR-compilation snapshot tests, and registry completeness tests remain owned by their phases; Phase 9 adds the top-of-stack E2E smoke and the CLI orchestration tests.

## Out of Scope

- Any new domain capability — Builder ops, overlay types, layouts, caption styles, IR vocabulary, render backends, or vision channels. Phase 9 is wiring plus an entry point only.
- A structured brief schema; `--brief` is free text (v1 out-of-scope per the plan).
- A script→TTS / zero-footage path; `--host` is required (ADR 0005; v1 out-of-scope).
- S3 storage; outputs go to filesystem paths via `blobs.py` with the single render-output writer as the S3-later seam (v1 out-of-scope).
- A distributed queue or HTTP/RPC transport; services are wired in-process behind interfaces, monolith-first (ADR 0003; v1 out-of-scope). The interfaces are the seam that makes the later transport change a non-rewrite.
- A human editor UI or an interactive/iterative CLI session; `videogen make` is a single batch command (human editor UI is v1 out-of-scope).
- MediaService enrichments — silence intervals, shot boundaries, image descriptions, salience — beyond the objective Media Manifest (v1 out-of-scope; addable later under the ADR 0003 facts-only rule).
- Alpha masks / non-clip media handling (v1 out-of-scope).

## Further Notes

- Phase 9 is the moment ADR 0003 and ADR 0005 become a runnable artifact rather than a design. The CLI is deliberately thin so that the "service ceremony" — interfaces and a job API in one process — pays off exactly as ADR 0003 intended: splitting later is a transport change, not a rewrite.
- The E2E smoke is the cheapest continuous guarantee that the whole pipeline stays wired; the reference-video full check is the richer, human-judged acceptance target. Keeping the two distinct keeps the fast suite fast while still naming the ambitious goal.
- The voiceover-as-master-clock invariant (ADR 0005) is what makes "output duration ≈ host clip length" a meaningful smoke assertion: the host recording sets the composition's duration, so a wildly different output length is a real signal that the pipeline is wrong.
- Because the CLI only orchestrates interfaces, the Phase 8b multi-model reality (authoring LLM + video-review LLM) and the Phase 7 async job model both pass through untouched — the command surfaces them, it does not re-implement them.
