# videogen

Talking-head-first short-form video generator: a creator's raw recording + b-roll + a
brief become a polished 9:16 short, driven entirely by a declarative **Composition** JSON.

Design is captured in [`CONTEXT.md`](CONTEXT.md) (glossary), [`docs/adr/`](docs/adr/)
(decisions), and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (build order). Per-phase
specs live in [`prd/`](prd/).

> **Status: Phase 0 (scaffold).** This is the toolchain and the empty package tree — no
> domain logic yet. Composition/IR types arrive in Phase 1.

## Layout

```
src/videogen/
  kernel/     # pure, render-free domain: Composition, IR, builder, validator, resolver, compile_ir
  plugins/    # registry-extensible: layouts/, overlays/, captions/
  backends/   # base.py (RenderBackend protocol) + remotion/ (subprocess wrapper + project/)
    remotion/project/   # Node/Remotion app: its own package.json; Node tooling scoped here
  services/   # media.py, render.py, authoring.py  (ADR 0003: three services, monolith-first)
  stores/     # composition_store.py, blobs.py      (snapshot undo + append-only journal)
  agent/      # tools.py, loop.py, review.py, prompts.py  (ADR 0004: tool-driven authoring)
  app/        # cli.py  (videogen make ...)
tests/
```

## Setup

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Node 18+ / npm. Phases 2+ also need
`ffmpeg`/`ffprobe` on `PATH`; Phase 8 needs `ANTHROPIC_API_KEY` set.

```sh
# Python environment (creates .venv from the lockfile)
uv sync

# Node deps for the Remotion render project
npm --prefix src/videogen/backends/remotion/project install
```

## Toolchain

All three run green on a fresh checkout (the known-good baseline every later phase builds on):

```sh
uv run ruff check    # lint
uv run mypy          # type check
uv run pytest        # test
```
