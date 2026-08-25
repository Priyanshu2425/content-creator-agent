# A typed BeatPlan binds creative direction to placement, so the Director stops re-deriving it

Status: Accepted

The creative-direction worker emits a typed **BeatPlan** (an ordered list of **Beats**) instead of
prose. A stable **beat id** is carried through asset generation (each generated asset is tagged with
the beat it serves), and the Director **executes the binding** — the asset bound to beat *B* is
placed on beat *B*'s span — rather than re-matching assets to moments by re-reading their text
descriptions. The Director keeps everything ADR [0008](./0008-director-dispatches-workers-in-loop.md)
gives it (it is still the only agent that authors kernel ops, and it still owns cross-layer
reconciliation); what it loses is the *guessing* about which asset goes where.

## Context — why (the diagnosis)

A real run (`renders/2026-06-19T19-18-33`) produced a broken narrative arc: warm "world-1" assets
(report card, parent embrace) landed in the **resolution** slot, the one resolution asset that *was*
generated ("parent and child assembling a robot") was **registered but never placed**, and several
static images were held 1.6–2.4s. The brief's payoff — parents building AI projects — never appeared
on screen even though an asset for it existed.

Root cause: intent travels as **prose through a scratchpad** and is re-interpreted three times — the
creative-direction worker writes a prose beat map, the b-roll worker re-interprets it into image
prompts, and the Director re-interprets *both* (prose + the generated assets' text descriptions) to
choose placements. There is **no machine-readable link** from a beat to the asset that serves it.
Each hop re-derives intent; drift compounds; and when a beat's asset is missing (e.g. a 429 during
generation) the Director silently back-fills with a wrong-role leftover. The system prompt already
*told* the model to "stay true to the creative direction" and to hold static images ≤1s — and it did
neither, because prose guidance is not an enforceable contract.

## Decision

1. **`BeatPlan` is the creative-direction proposal.** An ordered list of `Beat`s in **domain terms**
   (no kernel scene/region/op concepts), so the worker stays kernel-agnostic (ADR 0001/0002). A Beat
   carries: a stable `id`; a `transcript_span` (the *when*, anchored to transcript word indices the
   Director already owns — not seconds, so it survives re-timing); a narrative `role`
   (`world-1` / `world-2` / `climax` / `resolution` / `cta` / …); a one-line `intent`; and an
   `asset_spec` (`kind` ∈ {broll-image, broll-video, motion-graphic, host-aroll, stat-viz}, a
   generation brief, and treatment hints). Optional `layout_hint` / `emphasis`.
2. **Assets are beat-keyed.** Asset-generating workers (b-roll, motion-graphics) receive the beats
   that need visuals and return each asset **tagged with its `beat_id`** (`NewAsset` gains a
   `beat_id`). The asset↔beat link is explicit — a lookup, never a description re-match.
3. **The Director executes, then reconciles.** It maps each beat's `transcript_span` to a Scene +
   region and places the bound asset there in role order — deterministically. *Then* it does the job
   only it can (ADR 0008 §6): pacing certification, gap-fill punch-ins, collision/occlusion, brand
   enforcement, captions, SFX, the host-A-roll intercut policy, and `finish`.
4. **Missing-asset holes are explicit.** A beat whose asset failed to generate is a named gap the
   Director fills by a deterministic rule (punch-in on a neighbour, host A-roll, or drop the beat) —
   never by promoting a different-role leftover.
5. **A `host-aroll` beat kind exists.** The diagnosed run never scheduled the host because the prose
   plan omitted it, so the Director dumped the talking head into the tail. The BeatPlan can now
   reserve host beats (default: opening claim + CTA), keeping the product talking-head-first.

## Considered Options

- **Keep prose, just improve the Director prompt** — rejected: the prompt *already* carried the
  rules that were violated. Prose is non-deterministic and gives no test seam; this is the status quo
  that produced the bug.
- **Director-as-orchestrator runs placement; workers become pure generators** — rejected for the same
  reason ADR 0008/0011 rejected it: it retires 0008 and splits authoring across the search loop.
- **Creative direction emits full kernel ops (scenes/regions/timestamps)** — rejected: it couples the
  creative worker to the kernel (violating the ADR 0001/0002 worker-agnostic boundary), and the
  worker cannot certify pacing on a final timeline it never sees. The domain-term BeatPlan is the
  middle path: structured enough to execute, abstract enough to keep the worker decoupled and the
  Director the author.

## Consequences

- **ADR 0008 holds.** A BeatPlan is a richer *proposal*, still advisory — the Director may override or
  drop a beat and still emits every kernel op. Authorship does not move; only the proposal's *type*
  tightens (prose → typed), the same way ADR 0010 tightened captions from an enum to a registry.
- **Placement becomes testable** — the architectural payoff. `execute(beat_plan, assets) -> ops` is
  deterministic: a fake BeatPlan + stub assets can assert each asset lands on its beat's span/region,
  role order is preserved, and a missing-asset beat is handled. This is exactly the regression seam
  the pure-LLM placement path lacked (the open finding from the diagnosis), so the bug can be locked
  down.
- **Rollout mirrors `tot_enabled`** (ADR 0011): a `beat_plan_enabled` flag selects the typed path;
  the legacy prose creative-direction agent stays as fallback. A prose→BeatPlan parse step lets a
  weaker model that fumbles structured output degrade gracefully rather than fail.
- **Surface changes:** `dispatch_creative_direction` return type (prose `str` → `BeatPlan`); the
  b-roll / motion-graphics dispatch becomes beat-driven; `NewAsset` gains `beat_id`; the Director
  loop gains an "execute beat plan" phase before reconciliation. The kernel, the validator, and the
  other workers (SFX) are untouched.
- **Backstop already landed:** the static-image-hold rule is now a kernel validator warning
  (`STATIC_IMAGE_TOO_LONG`), independent of this change, so over-held stills are caught even on the
  legacy path.

## Resolved questions

- **Transcript span unit:** **word indices.** A `transcript_span` is `[start_word_idx, end_word_idx]`
  into the transcript the Director already owns. Survives re-timing; no seconds drift.
- **Scope of `host-aroll` beats:** **included now.** `host-aroll` is a first-class `Beat` kind, but it
  carries **no generation brief** — its "asset" is the existing talking-head track, so the beat is a
  pure placement reservation (span + intent). `execute()` binds a `host-aroll` beat to the host track
  rather than looking up a generated asset. This reserves host time up front (default: opening claim +
  CTA), directly closing the diagnosed "host dumped in the tail" failure, at the cost of one enum
  value and one execute() branch — no new generation worker.
- **Generation ownership:** **the b-roll worker stays the generator.** The Director passes it the
  beats that need visuals; CD and generation do **not** merge. Asset-generating workers (b-roll,
  motion-graphics) keep their role and return assets tagged with `beat_id`.
- **Flag name / default:** `beat_plan_enabled`, **defaulting on.** Diverges from `tot_enabled`
  (default off) deliberately: the typed path is the intended default behaviour, with the legacy prose
  agent retained only as a fallback for weaker models via the prose→BeatPlan parse step.
