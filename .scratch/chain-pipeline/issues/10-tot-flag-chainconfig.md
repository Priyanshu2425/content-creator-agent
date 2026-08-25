# `--tot` flag + ChainConfig + Gemini-missing error

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline. See
`docs/adr/0011-tot-worker-variant-deliberates-inside-the-worker.md`.

## What to build

Expose ToT deliberation as a knob. Add a `ChainConfig` that keeps `tot_enabled` **per-worker**
(creative direction, text hook — the only ToT-capable workers, Gemini-only per ADR 0011), defaulting
**off**. Add a single general `--tot` CLI flag that flips *both* ToT-capable workers; it is meaningful
on **both** pipelines (director-loop and chain), not chain-only. When `--tot` is set but Gemini is not
wired, **error clearly** (ToT workers are Gemini-only) rather than silently falling back to
single-pass.

## Acceptance criteria

- [ ] `ChainConfig` carries per-worker `tot_enabled`, default off.
- [ ] `--tot` flips both ToT-capable workers to their ToT variant.
- [ ] `--tot` works on both `--pipeline director-loop` and `--pipeline chain`.
- [ ] `--tot` without Gemini wiring errors clearly; no silent single-pass fallback.
- [ ] A test asserts the flag selects the ToT variant and the Gemini-missing error fires.

## Blocked by

- `04-creative-direction-to-composer-typed-passing.md`
