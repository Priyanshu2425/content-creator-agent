# videogen

Talking-head-first short-form video generator: a creator's raw recording + b-roll + a
brief become a polished 9:16 short, driven entirely by a declarative **Composition** JSON.

Design is captured in [`CONTEXT.md`](CONTEXT.md) (glossary), [`docs/adr/`](docs/adr/)
(decisions), and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (build order). Per-phase
specs live in [`prd/`](prd/).

> **Status: Phase 9 (end-to-end CLI).** The whole pipeline is wired behind one command: a host
> recording + optional b-roll + a free-text brief → ingest/probe/transcribe → an authoring agent
> builds a validated Composition → a video-capable reviewer gates finalization → an async render
> → a finished 9:16 mp4. See [Make a video](#make-a-video).

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

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Node 18+ / npm, and `ffmpeg`/`ffprobe` on
`PATH`. A live `videogen make` run also needs transcription (faster-whisper) and the two model
SDKs, plus their keys: `ANTHROPIC_API_KEY` (authoring) and `GOOGLE_API_KEY` or `GEMINI_API_KEY`
(the video reviewer).

```sh
# Python environment (creates .venv from the lockfile)
uv sync

# Everything a real end-to-end run needs (transcription + both model SDKs)
uv sync --extra live

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

## Make a video

The `videogen make` command (`app/cli.py`) is the single entry point over the whole stack. It is
deliberately thin — argument parsing and orchestration only — and wires the three services as
direct in-process calls behind their interfaces (ADR 0003, monolith-first).

```sh
uv run videogen make --host host.mp4 --broll a.png,b.mp4 --brief "50s short on X; open on the clip"
```

- `--host` (**required**) is the host-cam recording; its audio is the voiceover and master clock.
- `--broll` (**optional**) is a comma-separated list mixing stills and clips.
- `--brief` (**free text**) carries topic, length, style, and must-use moments — no schema.

It ingests and probes the inputs, transcribes the host audio, hands the agent a Media Manifest +
the brief, runs the Phase 8b finalization gate (render → video-review → corrective edits → re-render,
capped), and submits the final async render. The output mp4's path is printed on completion; a
failure is reported with the stage that broke and a non-zero exit.

The reference-video full check (a split-screen hook, the host with a slow zoom, a b-roll cut, and
synced captions) is the human-judged acceptance target; the automated guarantee that the pipeline
stays wired is the gated E2E smoke (`tests/test_e2e.py`, marked `integration`).

