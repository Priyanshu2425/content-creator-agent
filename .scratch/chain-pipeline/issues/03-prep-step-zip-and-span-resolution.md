# Prep step: deterministic zip + span resolution (pure module)

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

The deterministic, no-model **prep step** that sits between the chain's workers and the Composer.
`prep(beat_plan, assets, word_timings) -> list[(Beat{+resolved_span_s}, Asset|None)]`. Two lookups:
(a) **zip** each beat to its asset by `beat_id` — a beat with no matching asset yields an explicit
`None` pair; (b) **resolve** each beat's word-index `transcript_span` to concrete `[start_s, end_s]`
using the transcript word-timings. Output preserves beat/role order. This is a deep, pure module:
the determinism guarantees of the chain live here, and it is unit-testable with hand-built fixtures.

## Acceptance criteria

- [ ] A beat with a matching asset yields a paired tuple.
- [ ] A beat with no matching `beat_id` yields a `(Beat, None)` pair.
- [ ] A word-index span resolves to the correct `[start_s, end_s]` against a known word-timing table.
- [ ] Beat/role order is preserved in the output list.
- [ ] No model call anywhere in the module.
- [ ] Unit tests cover all of the above with fixtures (prior art: `tests/test_compile_ir.py`).

## Blocked by

- `01-beatplan-types-creative-direction-emits-beatplan.md`
