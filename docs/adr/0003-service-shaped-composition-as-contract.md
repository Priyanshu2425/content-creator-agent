# Service-shaped around the Composition contract, monolith-first

The system is three services — **AuthoringService** (hosts the Agent, builds + validates the Composition), **MediaService** (objective facts only: ingest, probe, transcribe, resolve `id → path`), **RenderService** (Composition → IR → backend → video, as an async job) — plus a **shared kernel library** (Composition schema/types + the type Registry) that all three import. The **Composition JSON is the message contract** between them. Services are defined as Python interfaces and wired as **direct in-process calls** for v1 (one deployable); the transport can become HTTP + a real queue later without redesign. Renders run in a background worker (`submit_render → job_id → status → artifact`).

We chose this over the originally-proposed stateful **`VideoEditor` object**, which would conflate three different relationships to the document — mutation, media ownership, and rendering — into one god-object. Splitting by producer/consumer of the Composition keeps each piece single-purpose. We chose monolith-first over standing up distributed infra immediately so we get async-render benefits and clean boundaries without operating queues/RPC before the product is validated.

## Consequences

- A multi-minute render never blocks the Agent loop or a UI.
- The "service" ceremony (interfaces, a job API) exists even though v1 runs in one process — deliberate, so splitting later is a transport change, not a rewrite.
- MediaService computes only objective facts; all creative decisions stay in the Agent. Objective enrichments (silence intervals, shot boundaries, image descriptions, salience) may be added later under that same rule without blurring the boundary.
