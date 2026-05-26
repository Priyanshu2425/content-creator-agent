# PRD — Phase 7: Stores + RenderService

## Problem Statement

Through Phase 6 the Composition has been treated as an in-memory value: the kernel builds it, validates it, resolves it, and compiles it to IR, and the Remotion backend renders it synchronously inside a test or a script. Two things are missing before the system can host an authoring Agent (Phase 8) and a real end-to-end CLI (Phase 9).

First, there is no durable home for the Composition. Per ADR 0003 the Composition JSON *is* the contract between services, and the persistence decision recorded in the plan states the Composition is the **source of truth**, with **snapshot undo** and an **append-only audit journal**. None of that exists yet. An authoring Agent that calls Builder ops one at a time (ADR 0004) needs to undo a bad op, and a human or a debugging session needs an auditable record of what happened to the document. Without a store, every op mutates an ephemeral value with no recovery and no history.

Second, rendering is synchronous, and a real render is multi-minute (Remotion shelling out to Node). ADR 0003 is explicit: a multi-minute render must never block the Agent loop or a UI. The Agent's tool-use loop and any future UI need to fire a render and keep working, polling for status and progress, collecting the artifact when it is ready. The synchronous call path cannot support that.

Third, render outputs and other blobs are written ad hoc by tests. There is no single place that owns filesystem paths and the act of writing a render output, and no seam for moving to S3 later — which the plan defers but explicitly wants to be a later transport change, not a rewrite.

## Solution

Phase 7 delivers three things, all in service of ADR 0003 (service-shaped, Composition-as-contract, monolith-first) and the persistence decision (snapshot undo + append-only journal).

**CompositionStore** (`stores/composition_store.py`) holds Compositions in memory with file persistence, treating the Composition as the source of truth. It supports snapshot-based undo/redo and maintains an append-only audit journal of operations applied to a Composition. The store is the durable surface the AuthoringService and Builder will write through in Phase 8; here it is built and tested standalone. Undo/redo is snapshot-based (not op-replay), consistent with ADR 0001's rejection of replay-based state: the store keeps document snapshots and moves a cursor across them. The journal is append-only and records what was done, in order, as an audit trail — distinct from the undo snapshot stack.

**blobs.py** (`stores/blobs.py`) owns filesystem path layout for artifacts and exposes a single render-output writer — the one place a finished render is written to storage. It is built with an S3-later seam: the path/IO surface is an interface whose only v1 implementation is filesystem, so swapping to S3 later is implementing the seam, not rewriting callers. This matches the plan's deferral of S3 to "later, behind a seam."

**RenderService** (`services/render.py`) becomes asynchronous. It exposes `submit_render(composition) → job_id`, runs the actual Composition → IR → backend → video work on a background worker (a `concurrent.futures` ThreadPoolExecutor with an in-memory job registry, per Tech choices), and exposes status/progress polling and artifact retrieval keyed by `job_id`. `submit_render` returns immediately with a `job_id`; the caller polls. This satisfies ADR 0003's non-blocking requirement directly. The submit path continues to honor the Phase 4 global-validation gate: `submit_render` is the gate point where reported global validation issues block a render. The worker writes its finished artifact through `blobs.py`'s single writer.

All three remain wired as direct in-process Python objects behind interfaces (ADR 0003 monolith-first): the queue, RPC, and S3 are later transport changes the interfaces are shaped to absorb without redesign.

## User Stories

1. As a creator/host, I want my video to keep rendering in the background while I keep working, so that a multi-minute render never freezes the session.
2. As a creator/host, I want to undo a change to my video and get the previous version back exactly, so that a mistake is cheap to recover from.
3. As a creator/host, I want to redo a change I just undid, so that I can move back and forth while comparing.
4. As a creator/host, I want my Composition to survive being closed and reopened, so that I do not lose my edit.
5. As a creator/host, I want to check how far along a render is, so that I know whether to wait or keep editing.
6. As a creator/host, I want to retrieve the finished mp4 once a render completes, so that I can watch and ship it.
7. As a creator/host, I want a clear failure if a render fails, so that I am not left polling forever.
8. As an authoring agent, I want `submit_render` to return a `job_id` immediately, so that my tool-use loop is never blocked by a render (ADR 0003, ADR 0004).
9. As an authoring agent, I want to poll a job's status and progress by `job_id`, so that I can decide whether to wait for the artifact or continue authoring.
10. As an authoring agent, I want to undo the last Builder op's effect on the Composition through the store, so that I can recover from an op I regret without rebuilding from scratch.
11. As an authoring agent, I want undo/redo to restore exact snapshots, so that I never get a subtly different document after undoing.
12. As an authoring agent, I want every op I apply recorded in the append-only journal, so that my authoring history is auditable when something goes wrong.
13. As an authoring agent, I want `submit_render` to refuse a render that fails the global validation gate, so that I do not spend minutes rendering a Composition that is known to be invalid.
14. As an authoring agent, I want to submit several renders and track each by its own `job_id`, so that I can render multiple variants or re-renders concurrently.
15. As an authoring agent, I want the Composition to be the single source of truth I read and write through, so that no derived or stale copy diverges from it (ADR 0003).
16. As a render-service developer, I want renders to run on a ThreadPoolExecutor with an in-memory job registry, so that v1 stays a monolith with no external queue (Tech choices, ADR 0003).
17. As a render-service developer, I want the job registry to track status, progress, the resulting artifact location, and any error per job, so that polling has something concrete to read.
18. As a render-service developer, I want the worker to report progress as the backend proceeds, so that callers see movement on a long render.
19. As a render-service developer, I want the worker to write the finished render through the single render-output writer in `blobs.py`, so that there is exactly one place that knows where outputs land.
20. As a render-service developer, I want a clean `submit_render → job_id → status → artifact` lifecycle, so that the API matches ADR 0003's stated job shape.
21. As a render-service developer, I want the async surface defined behind an interface, so that swapping the ThreadPoolExecutor for a real distributed queue later is a transport change, not a redesign.
22. As a render-service developer, I want a render failure captured as a terminal failed status with an error, so that a caller polling the job learns it failed rather than hanging.
23. As a platform maintainer, I want undo/redo implemented as snapshots, not op-replay, so that recovery stays consistent with the derived-state model of ADR 0001.
24. As a platform maintainer, I want the audit journal append-only, so that history cannot be silently rewritten.
25. As a platform maintainer, I want the journal kept distinct from the undo snapshot stack, so that auditing and recovery are not conflated.
26. As a platform maintainer, I want file persistence so the in-memory store can be flushed to and loaded from disk, so that the Composition is durable across process restarts.
27. As a platform maintainer, I want `blobs.py` to be the only writer of render outputs, so that the storage backend can move to S3 behind one seam (plan's S3-later deferral).
28. As a platform maintainer, I want all three pieces wired as in-process calls behind interfaces, so that monolith-first holds and a later split is a transport change (ADR 0003).
29. As a platform maintainer, I want the `submit_render` global-validation gate enforced in this service, so that the gate from Phase 4 has a real enforcement point.
30. As a platform maintainer, I want concurrent renders to not corrupt the shared job registry, so that the in-memory registry is safe under the executor's threads.
31. As a render-service developer, I want a still-render path to remain available (fast `render_still`) for the in-loop agent vision, so that Phase 8's perception is not forced through the async video-job lifecycle.
32. As a creator/host, I want a trailing black tail or other gap to render as the voiceover dictates, so that submitting a render with allowed gaps still succeeds (gaps warn, they do not block — Phase 4 coverage rules).

## Implementation Decisions

**Modules built.** `stores/composition_store.py` (CompositionStore), `stores/blobs.py` (path layout + single render-output writer with S3-later seam). **Modules modified.** `services/render.py` becomes the async RenderService.

**CompositionStore.** In-memory holding of Compositions keyed by id, with file persistence (flush to disk and load from disk). The Composition is the source of truth (ADR 0003); the store does not keep a separate derived representation. Two distinct structures back the store, per the persistence decision:

- A **snapshot undo/redo** mechanism. The store keeps a stack of full Composition snapshots and a cursor; undo moves the cursor back to a prior snapshot, redo moves it forward. This is snapshot-based, not op-replay-based, consistent with ADR 0001's rejection of replay for state — recovering a prior document is restoring a snapshot, not re-running ops. Snapshots are full Composition values (Pydantic models round-tripped through JSON per the Phase 1 serialization), so an undo yields an exact prior document.
- An **append-only audit journal**. Each applied operation appends an entry recording what was done, in order. The journal is append-only — entries are never mutated or removed — and is kept separate from the undo snapshot stack, since auditing (the full ordered history of what happened) and undo (navigating snapshots) are different concerns.

The store's interface is the durable write surface the Builder/AuthoringService will use in Phase 8; in this phase it stands alone and is exercised directly.

**blobs.py.** Owns filesystem path layout for render artifacts (e.g. a `renders/<id>.mp4` convention) and exposes a single render-output writer — the one entry point that persists a finished render. The path/write surface is defined as an interface (the seam); the v1 implementation is filesystem-only. S3 is out of scope for v1 (plan) but the seam exists so a later S3 writer is an added implementation, not a caller rewrite. All other modules obtain artifact locations and write outputs only through this module.

**RenderService (async).** API contract per ADR 0003:

- `submit_render(composition) → job_id` — validates against the global-validation gate (Phase 4: reported global issues block; gaps warn but do not block), enqueues the work on the ThreadPoolExecutor, registers a job in the in-memory job registry, and returns a `job_id` immediately without blocking.
- `status(job_id)` / progress polling — returns the job's current state from the registry: queued / running (with progress) / done (with artifact location) / failed (with error). A multi-minute render therefore never blocks the caller (ADR 0003).
- artifact retrieval — once done, the caller obtains the output location, which the worker wrote through `blobs.py`.

The worker performs the existing Composition → IR (`compile_ir`, driving plugins via the registry) → backend (`RemotionBackend.render_video`) pipeline, reports progress into the registry as it proceeds, and on completion writes the artifact through `blobs.py`'s single writer and marks the job done. A failure is captured as a terminal failed status with an error string, so a poller learns of failure rather than hanging.

**Concurrency model (Tech choices).** `concurrent.futures` ThreadPoolExecutor plus an in-memory job registry. This is the monolith-first v1: no external queue. The async surface is defined behind an interface so the executor + in-memory registry can be replaced by a real distributed queue later as a transport change without redesign (ADR 0003 consequence: the "service" ceremony exists even in one process so splitting later is a transport change, not a rewrite). The job registry must be safe for concurrent access by worker threads and pollers.

**Still path.** The fast `render_still(t)` path the backend exposes (ADR 0002) remains synchronous and is *not* routed through the async video-job lifecycle, because Phase 8's in-loop agent vision needs cheap stills, not minutes-long jobs (ADR 0004). Only `render_video` work goes through `submit_render`.

**In-process wiring.** CompositionStore, blobs, and RenderService are plain Python objects behind interfaces, called in-process (ADR 0003 monolith-first). The Composition JSON remains the message contract among services.

## Testing Decisions

Good tests here assert the externally observable lifecycle and recovery guarantees, not the internal layout of the registry or the snapshot stack.

**CompositionStore tests** assert behavior: after applying an op and undoing, the store yields a document equal to the pre-op snapshot; redo returns to the post-op document; undo past the beginning or redo past the end behaves predictably; the journal contains an append-only, in-order record of applied ops and is never shortened by an undo (undo and journal are independent — a key behavioral assertion); and a store flushed to disk and reloaded yields an equal Composition (file persistence round-trip, reusing the Phase 1 JSON round-trip prior art). Equality is asserted on the Composition value, not on internal fields of the store.

**RenderService tests** assert the async contract as external behavior: `submit_render` returns a `job_id` promptly and does not block for the render's duration; polling a `job_id` transitions through running to done; the done job exposes an artifact location that exists on disk; a forced backend failure yields a terminal failed status with an error rather than hanging; a Composition that fails the global-validation gate is refused at `submit_render` (no job, or an immediately-failed job, per the chosen contract) while one with only gap warnings is accepted; and multiple concurrently-submitted jobs each complete and are tracked independently. To keep these fast and deterministic, the backend can be a stub/fake `RenderBackend` (the protocol from Phase 2/base.py) so the service's job lifecycle is tested without invoking Node/Remotion — the render-path-touches-Remotion integration assertion stays in the existing per-phase render integration lane.

**blobs.py tests** assert that the single render-output writer places an artifact at the expected path and that the path/write surface is reached only through this module; the S3 seam is tested as an interface (a fake writer can stand in), not by hitting S3.

**Integration (render path lane, per the plan).** One end-to-end async submission with the real RemotionBackend: a fixture Composition → `submit_render` → poll to done → assert the artifact file exists, duration ≈ host length, and a sampled frame is non-black — the same assertions the plan prescribes for the render path, now exercised through the async job API.

Prior art to mirror: the Phase 1 JSON round-trip tests (for snapshot/persistence equality) and the existing per-phase render integration fixtures (for the end-to-end async submission).

## Out of Scope

- S3 (or any non-filesystem) storage. v1 is filesystem-only behind the `blobs.py` seam (plan out-of-scope).
- A real distributed queue or RPC transport. v1 is ThreadPoolExecutor + in-memory registry behind an interface (ADR 0003; plan out-of-scope).
- The authoring Agent, Builder-ops-as-tools, perception assembly, and the review sub-agent (Phases 8 / 8b). This phase builds the store and async render surface those phases will consume, but does not wire the Agent.
- The end-to-end CLI (`videogen make …`) — Phase 9.
- New overlay/effect types or kernel schema changes; the kernel and plugins are unchanged here.
- Multi-user / multi-document concurrency semantics beyond what the in-memory registry and store require for single-process v1 (no locking protocol across processes).
- Persisting the IR or backend intermediates; only the Composition (source of truth) and the final render artifact are persisted.

## Further Notes

- The defining requirement to keep in view: a multi-minute render must never block the Agent loop or a UI (ADR 0003). Every decision in the RenderService — immediate `job_id` return, background worker, poll-based status — exists to satisfy this, and the async-contract tests are the guard.
- Snapshot undo is deliberately not op-replay. ADR 0001 rejected replay for runtime state; the store follows the same instinct for recovery — restoring a document is restoring a snapshot, which is total and order-independent.
- The append-only journal and the undo snapshot stack are intentionally separate structures. Auditing wants the complete ordered history including undone work; undo wants navigable document states. Conflating them loses the audit trail on undo.
- The interfaces matter even though v1 runs in one process: the queue-later and S3-later seams are the whole reason the ceremony exists now (ADR 0003). Implement them as interfaces with one concrete v1 implementation each.
- The `submit_render` gate is where Phase 4's reported global validation finally bites — gaps warn (a trailing gap renders as a black tail, voiceover keeps playing, per the coverage rules), overlaps and other reported global errors block.
- Keep the synchronous `render_still` path out of the async job lifecycle so Phase 8's in-loop vision stays cheap; only `render_video` is a job.
