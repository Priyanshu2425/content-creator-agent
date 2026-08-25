# videogen

AI-powered short-form video generator. A creator's raw recording + b-roll + a brief become a polished 9:16 short, driven entirely by declarative **Composition** JSON.

## What it does

Feed it a host recording, some b-roll, and a free-text brief. An AI agent builds a full video composition — scenes, overlays, captions, effects — then renders it to mp4 through a Remotion backend.

```
videogen make --host host.mp4 --broll a.png,b.mp4 --brief "50s short on X; open on the clip"
```

## Architecture

```
src/videogen/
  kernel/          Composition JSON, IR, builder, validator, resolver, compile_ir
  plugins/         Registry-extensible layouts, overlays, captions
  backends/        remotion/ subprocess wrapper + Node/Remotion project
  services/        media.py, render.py, authoring.py
  stores/          composition_store.py, blobs.py (snapshot undo + journal)
  agent/           tools, loop, prompts, beat planning, chain pipeline, ToT
  app/             cli.py, settings.py, preview.py
  creation/        nano_banana (media creation)
tests/
```

## Prerequisites

- **Python 3.13+** — managed via [uv](https://docs.astral.sh/uv/)
- **Node 18+ / npm** — for the Remotion render backend
- **ffmpeg / ffprobe** — on `PATH` (used for probe + render)
- **API keys** (for live runs):
  - `ANTHROPIC_API_KEY` — authoring model
  - `GOOGLE_API_KEY` or `GEMINI_API_KEY` — video reviewer (Gemini)

## Setup

```sh
# Clone
git clone <repo-url>
cd content_creator_agent

# Python env (creates .venv from lockfile)
uv sync

# Full install with transcription + model SDKs
uv sync --extra live

# Node deps for Remotion render project
npm --prefix src/videogen/backends/remotion/project install

# Copy and fill in your API keys
cp .env.example .env  # or create manually
```

## Usage

### Run the full pipeline

```sh
uv run videogen make \
  --host host.mp4 \
  --broll a.png,b.mp4 \
  --brief "50s short on X; open on the clip"
```

| Flag | Required | Description |
|------|----------|-------------|
| `--host` | Yes | Host-cam recording (audio = voiceover + master clock) |
| `--broll` | No | Comma-separated stills and clips |
| `--brief` | Free text | Topic, length, style, must-use moments |
| `--pipeline` | No | `director-loop` (default) or `chain` |

### Toolchain

```sh
uv run ruff check        # lint
uv run mypy              # type check
uv run pytest            # tests (unit + integration)
uv run pytest -m "not integration"  # fast unit tests only
```

## Pipelines

Two pipeline strategies share the same front half (ingest → transcribe → ideal-cuts) but differ in how the composition is authored:

- **Director-loop** (default) — The Director agent pulls specialists on demand, adapts the plan, and builds the composition through validated kernel ops.
- **Chain** — Fixed-order pipeline: creative direction → broll/motion/text-hook (parallel) → prep → Composer → SFX → render. No adaptive model control.

## Design

Design docs live in:
- `CONTEXT.md` — glossary and composition model
- `docs/adr/` — architecture decision records
- `IMPLEMENTATION_PLAN.md` — build order
- `prd/` — per-phase specs
- `AGENTS.md` / `CLAUDE.md` — agent configuration

## License

Private — Buildspace Labs
