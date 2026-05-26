# PRD — Phase 8b: Review Sub-Agent (Finalization Gate)

## Problem Statement

Phase 8 gives us an authoring agent that builds a valid Composition one Builder op at a time, grounded in structured perception and an on-demand, image-based vision channel (a still frame at `t` and a scene preview strip). That channel is deliberately *image-based*: it answers framing, occlusion, and placement questions cheaply without paying for a full render. But there is a whole class of quality problems that simply cannot be judged from stills. Whether captions are *synced* to speech across their whole span, whether the pacing of cuts feels right, whether a `zoom` reads as smooth motion or a lurch, whether a caption is occluded only during part of its life as the host moves — these are full-motion judgements. A still at one instant can look perfect while the moving video is wrong.

ADR 0004 anticipated exactly this and reserved finalization for a separate, video-capable review sub-agent rather than having the authoring agent sample a few stills at the end and hope. The authoring agent is a text/tool model; it cannot natively watch an mp4. We need a distinct model that can, and we need a disciplined loop around it: render the real video, have the reviewer watch the whole thing, get back timestamped feedback, let the authoring agent apply edits, re-render, and re-review — bounded so it cannot loop forever. Without this gate, the system ships whatever the authoring agent produced on its first valid pass, with no full-motion check at all.

Phase 8b builds that gate: a `ReviewAgent` interface and a video-capable LLM implementation, wired into a finalization loop that amends the final-pass behavior described in ADR 0004.

## Solution

We introduce a **`ReviewAgent` interface** and a **video-capable LLM implementation** of it (for example Gemini), as specified in the Tech choices table. This implementation is **distinct from the text/tool authoring agent** of Phase 8 — the system becomes genuinely multi-model: an authoring LLM that calls Builder-op tools and a video-review LLM that natively watches mp4. The interface is what keeps the two decoupled and what lets the concrete video model be swapped without touching the loop.

We add a **finalization gate** that runs after the authoring agent reports it is done (Phase 8) and the Composition passes the `submit_render` validation gate. The gate is a bounded loop:

1. **Render** the current Composition to a full mp4 via RenderService's `render_video()` (Composition → IR → backend → video, as an async job per ADR 0003).
2. **Review** by handing the finished mp4 to the ReviewAgent, which **natively watches the full video** and returns **timestamped feedback** — concretely, observations keyed to timeline seconds about caption sync and occlusion, pacing, and framing.
3. **Apply edits**: the timestamped feedback is fed back to the Phase 8 authoring agent, which applies corrective Builder ops through its existing validated loop (each op still validated immediately; the Composition stays the source of truth).
4. **Re-render and re-review**, repeating the loop, **capped at N rounds (default 2)**. When the cap is reached or the reviewer reports no actionable issues, finalization is **done** and the last rendered mp4 is the shipped artifact.

Crucially, this divides the vision labor cleanly: **image stills and scene previews remain the in-loop channel** (Phase 8, owned by the authoring agent and routed through `render_still`), while **full-motion judgement is the review sub-agent's job** and consumes `render_video()` output. This is the explicit amendment to ADR 0004's final-pass: rather than the authoring agent sampling stills at the end, a dedicated video-capable reviewer watches the actual video.

## User Stories

1. As a creator/host, I want a video-capable reviewer to watch my finished short the way a person would, so that problems only visible in motion get caught before I ever see the output.
2. As a creator/host, I want caption timing checked against the moving video, so that captions that drift out of sync with my speech are caught even when a single frame looked fine.
3. As a creator/host, I want captions checked for occlusion across their whole life, so that a caption hidden behind me only while I move is flagged.
4. As a creator/host, I want pacing judged on the real video, so that cuts that feel rushed or draggy get noted and fixed.
5. As a creator/host, I want framing judged in motion, so that a zoom or pan that crops me badly or reads as a lurch is caught.
6. As a creator/host, I want the system to fix what the reviewer finds automatically, so that I get a polished result without a manual feedback round.
7. As a creator/host, I want the review-and-fix loop bounded, so that my video ships in reasonable time rather than being re-rendered endlessly.
8. As a review sub-agent, I want to receive the full rendered mp4, so that I can natively watch the actual video rather than infer quality from stills.
9. As a review sub-agent, I want to return feedback keyed to timeline seconds, so that the authoring agent knows exactly where each issue occurs.
10. As a review sub-agent, I want to report caption sync and occlusion issues, so that text problems that only manifest in motion are surfaced.
11. As a review sub-agent, I want to report pacing issues, so that the rhythm of scene cuts can be corrected.
12. As a review sub-agent, I want to report framing issues, so that mis-cropped or jarring camera moves can be corrected.
13. As a review sub-agent, I want to signal when I have no actionable issues, so that the finalization loop can stop early rather than burning a round.
14. As a review sub-agent, I want to be defined behind an interface, so that a specific video model can be swapped in or out without changing the finalization loop.
15. As an authoring agent, I want the reviewer's timestamped feedback delivered in terms I can act on, so that I can translate each note into corrective Builder ops.
16. As an authoring agent, I want to apply review edits through my existing validated op loop, so that every correction is still validated immediately and the Composition stays consistent.
17. As an authoring agent, I want each applied correction to keep the Composition passing the `submit_render` gate, so that a re-render is always against a valid document.
18. As an authoring agent, I want to keep using stills and scene previews for my own in-loop checks, so that the cheap image channel stays mine and full-motion review stays the reviewer's.
19. As a platform maintainer, I want the ReviewAgent to be a separate model from the authoring agent, so that the system is explicitly multi-model and each model does what it is best at.
20. As a platform maintainer, I want the review implementation to depend only on the ReviewAgent interface and the rendered artifact, so that swapping Gemini for another video model is a single implementation change.
21. As a platform maintainer, I want the finalization round cap configurable with a default of 2, so that I can trade output quality against render cost and latency.
22. As a platform maintainer, I want the gate to consume `render_video()` and never block on it synchronously in a way that wedges the loop, so that the async job model of ADR 0003 is honored.
23. As a platform maintainer, I want each render, each review, and each applied edit recorded in the Composition's audit journal, so that the finalization trajectory is reconstructable.
24. As a platform maintainer, I want the gate to terminate cleanly when the reviewer reports no actionable issues, so that we do not waste a render round on a video that is already good.
25. As a platform maintainer, I want the gate to terminate at the round cap even if the reviewer still has notes, so that the loop is guaranteed to end.
26. As a CLI user, I want finalization to be part of the authoring-to-render handoff, so that `videogen make` returns a reviewed mp4 rather than a first-pass one.
27. As a CLI user, I want the final artifact to be the last rendered mp4 from the gate, so that what I receive is exactly what the reviewer last watched.
28. As a review sub-agent, I want to distinguish issues I consider blocking from minor suggestions, so that the loop can prioritize the edits that matter most within its round budget.
29. As an authoring agent, I want to know which round of review I am responding to, so that I do not re-litigate notes I already addressed.

## Implementation Decisions

**New module: `agent/review.py` (ReviewAgent interface + video-LLM implementation).** This is the home reserved in Phase 8. It defines a `ReviewAgent` interface whose contract is: given a rendered mp4 artifact (and the Composition / Resolver timeline as context), return a structured set of timestamped feedback items. The concrete implementation is a video-capable LLM (e.g. Gemini) that natively watches the full video. The interface is the swap seam called for in the Tech choices table — the finalization loop depends on the interface, never on the specific model — keeping the system multi-model in the sense of ADR 0004's consequence note (authoring LLM + video-review LLM).

A representative feedback shape (illustrative of the decision, not a literal file):

```
ReviewFeedback = {
  items: [
    {
      at: seconds | { start: seconds, end: seconds },   # timeline-anchored
      category: "caption-sync" | "caption-occlusion" | "pacing" | "framing",
      severity: "blocking" | "suggestion",
      note: free-text observation,
    },
    ...
  ],
  no_actionable_issues: bool,   # lets the loop stop early
}
```

**Finalization gate in `services/authoring.py` (or an orchestration seam it owns).** AuthoringService gains a finalization step that runs after the Phase 8 authoring loop reports done and the Composition passes the `submit_render` gate. The step orchestrates the bounded loop: call RenderService `render_video()` to produce the mp4 (async job, ADR 0003); hand the artifact to the ReviewAgent; if the reviewer returns no actionable issues, finish; otherwise feed the timestamped feedback into the Phase 8 authoring agent so it applies corrective Builder ops (each immediately validated, Composition stays source of truth), then re-render and re-review. The loop is **capped at N rounds, default 2**. This is the precise amendment to ADR 0004's final-pass: full-motion review replaces end-of-run still sampling.

**Render path reuse.** The gate consumes `render_video()` from RenderService / the backend (ADR 0002, ADR 0003) — the same path Phase 7 stood up. No new render capability is introduced; Phase 8b is the first consumer of `render_video` for review purposes (the in-loop channel of Phase 8 used only `render_still`). This preserves the division: `render_still` for the authoring agent's in-loop image channel, `render_video` for the reviewer's full-motion channel.

**Feedback application via the existing authoring loop.** Corrections are not a new mutation path. The timestamped feedback is translated by the Phase 8 authoring agent into Builder-op tool calls inside its existing validated loop, so every review-driven edit gets the same immediate validation and the same audit-journal recording as original authoring (ADR 0004; ADR 0003 persistence). The authoring agent is told which review round it is responding to so it does not re-open already-addressed notes.

**Persistence interaction.** Each render, each review pass, and each applied edit is recorded against the Composition's append-only audit journal (Phase 7), making the full finalization trajectory reconstructable.

**Model and SDK.** The reviewer is a video-capable LLM behind the `ReviewAgent` interface, distinct from the Phase 8 authoring model (`claude-opus-4-7` / `claude-sonnet`), per the Tech choices table.

## Testing Decisions

A good test here asserts **the behavior of the finalization gate**, not the prose of the video model. The reviewer is non-deterministic and external, so the deterministic tests target the loop's control flow and the interface contract, with a fake ReviewAgent standing in for the real video model.

- **Gate control flow with a fake reviewer:** drive the finalization loop with a fake `ReviewAgent` that returns a scripted sequence of feedback — for example, blocking caption-sync notes in round 1, then `no_actionable_issues` in round 2. Assert the loop renders, reviews, applies edits through the authoring loop, re-renders, and terminates exactly when the reviewer signals clean. Assert the round cap (default 2) terminates the loop even when the fake reviewer keeps returning notes. This is the core external-behavior test of the phase.
- **Early termination:** with a fake reviewer that returns `no_actionable_issues` on the first pass, assert the loop does exactly one render and zero edit rounds, so a good first-pass video is not needlessly re-rendered.
- **Feedback-to-edit path:** assert that timestamped feedback fed to the authoring agent results in corrective Builder ops that are immediately validated and that the post-edit Composition still passes the `submit_render` gate before re-render. This reuses the Phase 4 kernel validator and Phase 8 loop prior art rather than re-testing them.
- **Interface fidelity / swap seam:** assert the finalization loop depends only on the `ReviewAgent` interface, by running it against two different fake implementations and confirming the loop is unchanged — evidence the Gemini implementation can be swapped per the Tech choices table.
- **Render channel separation:** with a fake backend that counts calls, assert the finalization gate uses `render_video()` and that the in-loop authoring channel still uses only `render_still` — confirming the Phase 8 / Phase 8b division of vision labor.
- **Live smoke (opt-in, gated on the video model's API key):** a thin run of the gate against the real video reviewer on a short rendered clip, asserting the loop terminates within the round cap and returns a final mp4. Kept separate from the deterministic suite; this folds into the Phase 9 E2E smoke, which exercises ingest → author → finalize → render end to end.

Per the plan's testing approach, IR-compilation snapshot tests, registry completeness, and per-phase render integration remain owned by their phases; Phase 8b tests sit at the finalization-loop and interface boundary.

## Out of Scope

- The Phase 8 authoring loop itself, its Builder-op tools, structured perception, and the in-loop still/scene-preview vision channel — all delivered in Phase 8 and only *consumed* here.
- The end-to-end CLI and in-process service wiring (Phase 9); Phase 8b delivers the gate, Phase 9 wires it into `videogen make`.
- Any new render capability; `render_video()` already exists from Phase 7. Phase 8b is its first review consumer.
- New overlay types, layouts, caption styles, or Builder ops; corrections use the existing kernel surface.
- A human-in-the-loop review or approval UI; finalization is fully automated within the round cap (human editor UI is v1 out-of-scope per the plan).
- Configurable, per-category review policies beyond the round cap (e.g. "always fix framing, never touch pacing"); the gate treats reviewer feedback uniformly within its rounds in v1.
- Multi-model fan-out (several reviewers voting); a single video-capable ReviewAgent is used in v1.
- S3 storage, distributed queue/RPC transport (v1 out-of-scope; monolith-first per ADR 0003).

## Further Notes

- The clean division of vision labor is the heart of this phase: stills and scene previews are the *in-loop* channel the authoring agent controls for cost; the full mp4 is the *finalization* channel the review sub-agent watches for quality. Conflating them was the failure mode ADR 0004 explicitly amended away from.
- The round cap (default 2) is the loop's termination guarantee. It must hold even when the reviewer is never fully satisfied — the last rendered mp4 at the cap is the shipped artifact. Early termination on `no_actionable_issues` is the optimization, not the guarantee.
- Because corrections flow back through the Phase 8 authoring loop, every review-driven edit inherits immediate validation and audit journaling for free. Phase 8b adds an orchestration layer and a new model, not a new mutation path or a new render path.
- The `ReviewAgent` interface is the multi-model boundary made concrete. Keeping the finalization loop dependent only on the interface is what lets the concrete video model evolve (or be replaced) without disturbing the gate — the same swappability discipline ADR 0002 applies to render backends.
