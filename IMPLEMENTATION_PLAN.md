# Implementation Plan — Talking-Head-First Short-Form Video Generator

## Context

We designed (across three `/grill-with-docs` sessions) a system that turns a creator's raw recording + b-roll + a brief into a polished 9:16 short, driven entirely by a declarative **Composition** JSON. Design captured in `CONTEXT.md` (glossary) and `docs/adr/0001–0005`.

**Committed approach: talking-head-first.** The build is re-centered so the first working product is the core talking-head experience — a host recording transcribed into **word-synced captions over the speaker** → mp4. Split-screen, b-roll, effects, and the Agent are *additive* phases layered on a working core. This ships value early and de-risks incrementally.

Guiding decisions (ADRs) the plan honors:
- **0001** — Composition = declarative scenes + overlay union + captions; runtime state is *derived*, never replayed.
- **0002** — Render goes through a neutral **IR**; backends implement `IR → frames`; plugins are backend-agnostic (`to_ir`). Remotion is first backend.
- **0003** — Three services (Authoring / Media / Render) + shared kernel; Composition JSON is the contract; **monolith-first, service-shaped**.
- **0004** — Agent authors via validated **Builder ops** (imperative authoring → declarative doc); structured perception + on-demand vision.
- **0005** — Kickoff = host recording (its audio = `voiceover`/master clock) + assets + brief.
- Persistence (chat) — Composition is source of truth; snapshot undo + append-only audit journal.

**Language:** Python. Remotion is JS, so `RemotionBackend` shells out to a Node subprocess.

Reconciliation: a plugin's render facet is a **pure `to_ir(params) → IR fragment`** (no render deps). Backends interpret the **IR's 3 layer kinds**, *not* per-overlay-type code. So `plugins/<type>/` holds `contract.py` + `ir.py`; the only Remotion code lives in `backends/remotion/`.

## Tech choices

| Concern | Choice | Why |
|---|---|---|
| Packaging | `uv` + `pyproject.toml`, `src/` layout | modern, fast |
| Models/validation | **Pydantic v2** | Composition + IR types, two-tier validation, JSON (de)serialization |
| Lint/type/test | `ruff`, `mypy`, `pytest` | standard |
| Media probe | `ffprobe` via subprocess | duration/dims/fps |
| Transcription | `faster-whisper` (`word_timestamps=True`) | word-level timings for captions; WhisperX = higher-accuracy alt |
| Render backend | Remotion (Node) via `subprocess` (`npx remotion render` / `still`), IR as `--props` JSON | matches 0002 |
| Authoring agent | Anthropic SDK, `claude-opus-4-7` (or sonnet), tool-use loop | Builder ops as tools; in-loop vision = still frame + scene preview (images) |
| Review sub-agent | video-capable LLM (e.g. Gemini) behind a `ReviewAgent` interface | natively watches the full mp4 → timestamped feedback at finalization |
| Async worker (v1) | `concurrent.futures` ThreadPoolExecutor + in-memory job registry | monolith-first; queue later behind interface |

## Repo structure (to create)

```
pyproject.toml
src/videogen/
  kernel/
    composition.py   # Pydantic: Composition, Asset, Audio, Scene, Ref, Transition, Overlay, Caption
    ir.py            # IR, Layer (media|text|audio), common fields, Value/Keyframe track, easing
    registry.py      # plugin registry + completeness check
    builder.py       # entity-complete CRUD ops + add_captions_from_transcript
    validator.py     # two-tier: local (hard) + global (reported, gated)
    resolver.py      # (composition, t) -> frame description  (agent eyes + sanity)
    compile_ir.py    # Composition -> IR, driving plugins.to_ir via registry
  plugins/
    layouts/  full/, split_h/            # contract: region slots + geometry
    overlays/ zoom/, pan/, insert/       # contract.py + ir.py (to_ir)
    captions/ styles.py                  # pill, word_bold, kinetic
  backends/
    base.py                              # RenderBackend protocol: render_video, render_still
    remotion/
      __init__.py                        # Python wrapper (subprocess)
      project/                           # Node/Remotion app: IR JSON -> 3 layer-kind components + keyframe sampler
  services/
    media.py        # ingest, probe, transcribe, resolve  (facts-only, 0003)
    render.py       # submit_render -> job_id, worker, status/progress
    authoring.py    # agent loop host, perception assembly
  stores/
    composition_store.py  # in-mem + file; snapshot undo/redo; append-only journal
    blobs.py              # filesystem paths; single render-output writer (S3-later seam)
  agent/
    tools.py        # Builder ops -> Claude tool schemas
    loop.py         # authoring tool-use loop; in-loop vision = still + scene preview
    review.py       # ReviewAgent interface + video-LLM impl (watches full mp4 -> feedback)
    prompts.py
  app/
    cli.py          # e2e: --host required, --broll optional, --brief
tests/
```

## Build order (talking-head-first; core ships at Phase 3)

| Phase | Deliverable | Maps to |
|---|---|---|
| **0. Scaffold** | `uv` project, package layout, ruff/mypy/pytest | — |
| **1. Contract types** | `kernel/composition.py` + `kernel/ir.py` Pydantic models; round-trip + validation unit tests | 0001, IR vocab |
| **2. Host-only render path** | Minimal `MediaService` (ingest/probe/resolve, fs paths); host_cam → a single `full` scene Composition → minimal `compile_ir` (media kind) → Remotion `project/` (media + audio mux, keyframe sampler) → `RemotionBackend.render_video`/`render_still` → **mp4 of the talking head**. De-risks the Python↔Remotion↔IR seam on the simplest case. | 0002, 0003, 0005 |
| **3. Transcription → captions ⇒ MVP** | `MediaService.transcribe` (faster-whisper word timings); caption styles (`pill`/`word_bold`/`kinetic`); captions → IR `text` layers (kinetic = opacity/scale keyframes). **MVP milestone: talking head + word-synced captions → mp4.** | 0005, IR animation |
| **4. Builder + Validator + Resolver** | Pure kernel, **TDD**: CRUD ops (scenes/captions first) + `add_captions_from_transcript`; two-tier validation (local hard / global reported + `submit_render` gate); Resolver timeline. Composition now built programmatically, not hand-written. | 0004, coverage rules |
| **5. Layouts + b-roll + Registry** | `registry.py` + completeness check; `full`/`split-h` layout plugins; full-frame b-roll scenes; transitions (cut default + crossfade); `compile_ir` driven via registry. | 0001, 0002 |
| **6. Effects** | Overlay plugins `zoom`/`pan`/`insert` (contract + `to_ir` keyframes); spatial region targets (`full`/`top`/`bottom`); z-order. | 0002, IR animation |
| **7. Stores + RenderService** | `CompositionStore` (in-mem + file, snapshot undo/redo, append-only journal); `blobs.py` (fs paths + single render-output writer); async `RenderService` (`submit_render → job_id`, status/progress). | 0003, persistence |
| **8. AuthoringService + Agent** | Builder ops as Claude tools; authoring loop w/ structured perception (Manifest + Composition + Resolver timeline + validation report) + on-demand **still frame** (`render_still`) and **scene preview** (image strip). | 0004 |
| **8b. Review sub-agent** | `ReviewAgent` interface + video-capable LLM impl. Finalization gate: `render_video()` → review sub-agent **watches the full mp4** → timestamped feedback → authoring agent applies edits → re-render → re-review, capped at N rounds (default 2), then done. | 0004 (amends final-pass) |
| **9. E2E CLI** | `videogen make --host host.mp4 [--broll a.png,b.mp4] --brief "…"` → ingest/transcribe → agent authors → `submit_render` → mp4. Services wired in-process behind interfaces. | 0003, 0005 |

## Testing approach

- **Kernel (TDD, from Phase 4):** Builder ops, two-tier validator (overlap = error, gap = warning, region-validity, caption alignment), Resolver. Tests first.
- **IR compilation:** snapshot tests — Composition → expected IR JSON (grows per phase: host-only → captions → layouts → effects).
- **Registry (from Phase 5):** contract test asserting completeness (every overlay type compiles to IR; backend handles every IR kind) — fails build on drift.
- **Render path (integration):** per-phase fixture Composition → mp4; assert file exists, duration ≈ host length, a sampled frame is non-black.
- **MVP acceptance (end of Phase 3):** a real host clip → mp4 with on-time, correctly-styled captions.
- **E2E smoke (Phase 9):** host clip + one b-roll + short brief → mp4; job completes.

## Out of scope (v1)

S3 storage, script→TTS / no-footage path (host recording required), distributed queue/RPC, alpha masks (clip-only), structured brief schema (free-text brief), human editor UI, MediaService enrichments (silence/shot/salience).

## Verification (end-to-end)

1. `uv sync`; install Node deps in `backends/remotion/project` (`npm i`); ensure `ffmpeg`/`ffprobe` on PATH; set `ANTHROPIC_API_KEY`.
2. `uv run pytest` — all phase tests green (kernel units, IR snapshots, registry completeness, render integration).
3. **MVP check (after Phase 3):** render a sample host clip → `renders/<id>.mp4` shows the talking head with word-synced captions in the three styles.
4. **Full check (after Phase 9):** `uv run videogen make --host samples/host.mp4 --broll samples/tweet.png --brief "50s short on X; open on the clip; cite the tweet"` → mp4 with split-screen hook, host w/ slow zoom, b-roll cut, and synced captions — the reference-video shape.
