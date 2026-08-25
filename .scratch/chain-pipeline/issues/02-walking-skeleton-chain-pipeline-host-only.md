# Walking-skeleton chain pipeline (host-only)

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline. See
`docs/adr/0013-chain-pipeline-fixed-order-alternative-to-director-loop.md`.

## What to build

The thinnest end-to-end chain run that produces a finished mp4. Add the `--pipeline
{director-loop, chain}` CLI flag (default `director-loop`, which must keep today's behavior exactly).
Introduce the **pipeline strategy** seam: the shared front half (ingest → transcribe → ideal-cuts)
stays in `Pipeline`; a strategy owns the back half. `DirectorLoopStrategy` wraps the existing path
unchanged. `ChainStrategy` (skeleton) runs *no workers yet* and invokes a skeleton **Composer** — a
single no-tools Opus 4.8 Claude Code SDK call that emits a host-only `Composition` directly from the
transcript + ideal cuts. The shared compile/render tail then produces the mp4.

This proves the whole spine wires together (CLI → strategy fork → Composer call → Composition →
compile → render) before any worker is added.

## Acceptance criteria

- [ ] `make --pipeline director-loop` is byte-for-byte the current default behavior.
- [ ] `make --pipeline chain` runs end-to-end and produces a playable mp4.
- [ ] The Composer emits a `Composition` directly (no kernel ops, no Builder ops).
- [ ] The shared front half is written once; both strategies reuse it.
- [ ] A test exercises the chain strategy with a stubbed model and asserts a Composition is produced
      and compiled.

## Blocked by

None - can start immediately.
