# Role-check predicate + Composer re-prompt loop

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

Nail shut the ADR 0012 wrong-role back-fill bug for the chain's LLM-placed Composition, and add the
Composer's validation loop. Build the pure predicate
`wrong_role_backfill_violations(composition, beats)`: for every placed asset, the role of the beat it
was generated for (`asset.beat_id → beat.role`) must equal the role of the beat occupying the span it
landed on; any mismatch is a violation. Wire it into the Composer alongside the IR validator: after
generation, run both; on any violation or validator failure, **re-prompt** the same no-tools call with
the errors appended, bounded retries. Exhausting retries is a **fatal** Composer failure.

## Acceptance criteria

- [ ] The predicate is pure (Composition + BeatPlan → violations) with no model call.
- [ ] An asset on a same-role span → no violation; on a different-role span → exactly that violation.
- [ ] An IR-validator failure triggers a bounded re-prompt with errors appended.
- [ ] A role violation triggers a re-prompt.
- [ ] Exhausting retries raises a fatal Composer error.
- [ ] Tests cover the predicate (fixtures) and the re-prompt behavior (stubbed model).

## Blocked by

- `05-beat-keyed-asset-generators-broll-mg.md`
