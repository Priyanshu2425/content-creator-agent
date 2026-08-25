# SFX post-Composer stage (reuse SFXAgent)

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline. See
`docs/adr/0009-sfxagent-single-sfx-authority.md`.

## What to build

Add SFX as a fixed stage after the Composer. Reuse **SFXAgent unchanged**: it reads the near-final
Composition the Composer emitted and **layers sound onto it** (the Composer owns structure; SFX owns
sound — it does not regenerate a competing Composition). The stage no-ops cleanly when there is
nothing to score, and an SFX failure **degrades** to a silent-SFX video.

## Acceptance criteria

- [ ] SFXAgent runs after the Composer, fed the Composer's Composition.
- [ ] SFX adds only a sound layer; it does not author a competing Composition.
- [ ] Nothing-to-score → clean no-op.
- [ ] An SFX failure leaves a renderable (silent-SFX) video.
- [ ] A test asserts SFX layers onto the Composer output and a failure degrades.

## Blocked by

- `05-beat-keyed-asset-generators-broll-mg.md`
