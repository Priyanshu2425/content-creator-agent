# videogen

Talking-head-first short-form video generator: a creator's raw recording + b-roll + a
brief become a polished 9:16 short, driven entirely by a declarative **Composition** JSON.

Design is captured in [`CONTEXT.md`](CONTEXT.md) (glossary), [`docs/adr/`](docs/adr/)
(decisions), and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (build order). Per-phase
specs live in [`prd/`](prd/).

> **Status: Phase 2 (host-only render path).** The Python↔Remotion↔IR seam is proven on the
> simplest case: a host recording → a single `full`-scene Composition → neutral IR → an mp4 of
> the talking head. Captions (the MVP) arrive in Phase 3.

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

## Render path (Phase 2)

A Composition compiles to a backend-agnostic **IR** (`kernel/compile_ir.py`), and the
`RemotionBackend` (`backends/remotion/`) shells out to the co-located Node/Remotion app
(`backends/remotion/project/`), passing the IR as `--props` JSON, to produce an mp4 or a single
still. The backend dispatches on the IR's three layer kinds (`media`/`audio`/`text`), never on
overlay types — the only Remotion code lives in `project/` (ADR 0002).

Running the render path needs `ffmpeg`/`ffprobe` on `PATH` and the Node deps installed (see
Setup). The render integration tests (`tests/test_render_path.py`, marked `integration`) generate
a fixture host clip, render it, and assert the output exists, its duration ≈ the host length, and
sampled frames are non-black. They skip automatically if the toolchain is absent. Run only the
fast unit + snapshot tests with:

```sh
uv run pytest -m "not integration"
```

