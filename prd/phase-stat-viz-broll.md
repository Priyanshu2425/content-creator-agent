# Stat-Viz B-Roll Tools for GenerateBrollAgent

## Problem Statement

When a creator's narration states a numerical claim — a percentage, a ratio, a before/after comparison — the existing pipeline can only respond with a static generated image (a "stat card" PNG). Static cards are low-impact: they cannot animate a number counting up, a bar filling in, or a ratio icon revealing itself. The visual support for statistical claims is weaker than it could be, and there is no mechanism to produce animated data-visualisation clips automatically.

## Solution

Extend `GenerateBrollAgent` with five new tools — `render_counter`, `render_bar`, `render_gauge`, `render_before_after`, and `render_ratio` — that produce animated Remotion clip b-roll assets in place of static images for numerical claims. Each tool shells out to a dedicated Remotion composition in the existing Remotion project, merging LLM-supplied data parameters with a per-video `StyleBrief` injected by the Python layer. The resulting clip is a `GeneratedSlot` of `kind="video"`, ingested into the pipeline exactly like any other generated b-roll asset.

The `generate_image` tool remains unchanged for non-stat claim types. For "Data / statistic" claims, the animated viz tools are always used — `generate_image` is never called for a numerical stat.

## User Stories

1. As `GenerateBrollAgent`, I want a `render_counter` tool, so that I can produce an animated count-up clip for a single percentage or number claim (e.g. "revenue grew 40%").

2. As `GenerateBrollAgent`, I want a `render_bar` tool, so that I can produce an animated bar-comparison clip for two-value comparisons (e.g. "Company A: 80%, Company B: 20%").

3. As `GenerateBrollAgent`, I want a `render_gauge` tool, so that I can produce an animated progress-ring clip for progress-toward-a-goal claims (e.g. "raised $3M of a $10M target").

4. As `GenerateBrollAgent`, I want a `render_before_after` tool, so that I can produce an animated reveal clip for state-change claims, both numeric and qualitative (e.g. "manual: 3 hours → automated: 10 minutes").

5. As `GenerateBrollAgent`, I want a `render_ratio` tool, so that I can produce an animated ratio-icon clip for fractional claims (e.g. "1 in 3 users churn").

6. As `GenerateBrollAgent`, I want the system prompt to route all "Data / statistic" claim types to the animated viz tools, so that I never fall back to a static stat card for a numerical claim.

7. As `GenerateBrollAgent`, I want each animated viz tool to have a tight, format-specific input schema, so that I cannot accidentally pass `numerator`/`denominator` to a counter call or `value_b` to a gauge call.

8. As `GenerateBrollAgent`, I want to pass only the data parameters per tool call (value, label, unit, duration), so that style decisions (color, font, background) are not my responsibility and cannot vary call-to-call within a video.

9. As the pipeline, I want the Python dispatch layer to inject a `StyleBrief` into every `render_*` tool call, so that all stat-viz clips within a single video share a coherent visual style without the LLM choosing colors.

10. As the pipeline, I want the `StyleBrief` placeholder for v1 to be hardcoded sensible defaults, so that the system works before the upstream design agent that will eventually supply it is built.

11. As the pipeline, I want `render_*` tool calls to be dispatched in parallel via the existing `ThreadPoolExecutor`, so that multiple stat-viz renders within one agent turn do not serialize.

12. As the pipeline, I want a successful `render_*` call to return a `GeneratedSlot` of `kind="video"` with the clip path, so that the slot is ingested via `MediaService` exactly like any other generated b-roll asset.

13. As the pipeline, I want a failed `render_*` call to return an error tool result and skip the slot, so that render failures behave identically to failed `generate_image` calls and do not halt the agent.

14. As `AuthoringAgent`, I want rendered stat-viz clips to appear in the `MediaManifest` as video assets with descriptions, so that I can place them as full-frame b-roll Scenes at the timestamps the IdealCuts plan flagged.

15. As `GenerateBrollAgent`, I want the GENERATEBROLL PLAN format to include an "Animation approach" field for stat slots, so that the plan narration records which animated format was chosen and why.

16. As a platform maintainer, I want a `StatVizRenderer` with a simple, stable interface, so that it can be tested in isolation from `GenerateBrollAgent` and from the Remotion project.

17. As a platform maintainer, I want the five Remotion stat-viz compositions to live in the existing Remotion project alongside `Main`, so that there is only one Node project, one `npm install`, and one subprocess driver to maintain.

18. As a platform maintainer, I want each stat-viz composition to accept a `StyleBrief` as part of its props, so that the upstream design agent can change the visual language of all compositions by changing one object.

19. As a platform maintainer, I want `RemotionBackend` to gain a `render_clip` method that takes a composition id and a raw props dict, so that stat-viz rendering reuses the existing subprocess invocation without touching `render_video` or `render_still`.

20. As a future developer, I want the `StyleBrief` to be a named data class with a clear interface, so that wiring in the upstream design agent's output is a one-line change.

21. As a creator, I want `render_gauge` to accept an arbitrary `max` value (not just 0–100), so that claims like "raised $3M of a $10M goal" render correctly as a progress ring.

22. As a creator, I want `render_before_after` to accept string values for both sides, so that qualitative comparisons ("manual process → automated") render correctly alongside numeric ones ("3 hours → 10 minutes").

23. As `GenerateBrollAgent`, I want the `slot` field on every `render_*` tool to match the GENERATEBROLL PLAN slot number, so that plan tracking and logging are consistent across image and video tools.

24. As a platform maintainer, I want `GenerateBrollAgent` to accept an optional `stat_viz_renderer` at construction time, so that it degrades gracefully to image-only mode when no renderer is supplied and existing tests do not require a Remotion subprocess.

## Implementation Decisions

**New module: `StatVizRenderer`** — A single deep module with a stable interface:

```
StatVizRenderer.render(
    format: Literal["counter", "bar", "gauge", "before_after", "ratio"],
    data: dict,        # format-specific params from the tool call
    style: StyleBrief,
    out_path: Path,
    fps: int = 30,
) -> Path
```

Internally it maps `format` → composition id, merges `data` and `style` into a props dict, and delegates to `RemotionBackend.render_clip`. Nothing else belongs in this class. It is importable and testable without `GenerateBrollAgent` or any LLM.

**New method: `RemotionBackend.render_clip(composition_id, props, out_path)`** — Shells out to `npx remotion render <entry> <composition_id> <out_path> --props <json>`. Same subprocess invocation as `render_video`, different composition id and props shape. Does not take an `IR`; the props dict is serialized directly. `render_video` and `render_still` are unchanged.

**New data class: `StyleBrief`** — `background: str`, `primary: str`, `accent: str`, `font_family: str`. For v1, a module-level `DEFAULT_STYLE_BRIEF` constant supplies sensible defaults (dark background, white primary, orange-ish accent, Inter font). The upstream design agent will replace this constant with a supplied object when it is built; the interface is already the seam.

**Five Remotion compositions in the existing project** — Registered in `Root.tsx` alongside `Main`:

| Composition id | Format | Key props (data side) |
|---|---|---|
| `StatVizCounter` | counter | `value: number`, `unit: string`, `label: string`, `duration_s: number` |
| `StatVizBar` | bar | `label_a`, `value_a: number`, `label_b`, `value_b: number`, `unit`, `duration_s` |
| `StatVizGauge` | gauge | `value: number`, `max: number`, `label: string`, `unit: string`, `duration_s` |
| `StatVizBeforeAfter` | before_after | `label_a: string`, `value_a: string`, `label_b: string`, `value_b: string`, `duration_s` |
| `StatVizRatio` | ratio | `numerator: int`, `denominator: int`, `label: string`, `duration_s` |

Every composition also accepts the `StyleBrief` fields (`background`, `primary`, `accent`, `font_family`) as top-level props, merged in by `StatVizRenderer` before the shell-out.

**Five new tools on `GenerateBrollAgent`** — Tight per-format schemas; no cross-format optional fields. Each tool has a `slot: integer` field matching the plan slot, a `duration_s: float` field (the LLM reads this from the IdealCuts window and Python clamps it to the window duration before dispatch), and only the data fields that format needs. `aspect_ratio` is not a parameter — the Python layer derives it from the pipeline's `platform` setting (9:16 for Instagram/TikTok, 16:9 for YouTube).

**Modified `GenerateBrollAgent`** — Constructor gains `stat_viz_renderer: StatVizRenderer | None = None`. When `None`, the five render tools are omitted from the tool list entirely, preserving image-only behaviour. `_dispatch_one` gains branches for each `render_*` tool name that call `StatVizRenderer.render`, save the clip to `dest/slot_{n}_{uuid}.mp4`, and return a `GeneratedSlot(kind="video", ...)`. `_dispatch_parallel` is unchanged — the `ThreadPoolExecutor` already parallelises all tool calls in a turn, including Remotion renders.

**System prompt update** — The claim-type taxonomy table in `GenerateBrollAgent`'s system prompt is updated: "Data / statistic" rows now map to the appropriate `render_*` tool rather than `generate_image`. A new decision table maps claim sub-types to formats: single number/percentage → `render_counter`; two-value comparison → `render_bar`; progress-toward-goal → `render_gauge`; state change (numeric or qualitative) → `render_before_after`; "X in N" / "X out of Y" → `render_ratio`. The GENERATEBROLL PLAN output format gains an "Animation approach" field for stat slots in place of "Image approach".

**`StyleBrief` injection** — `StatVizRenderer.render` always receives the `StyleBrief`; `GenerateBrollAgent._dispatch_one` reads it from `self._style_brief` (set at construction time, defaulting to `DEFAULT_STYLE_BRIEF`). The LLM never sees style params in the tool schema.

## Testing Decisions

A good test asserts the external contract of a module — its output given controlled inputs — without asserting how it internally achieves that output. Tests should not stub `StatVizRenderer` internals or assert on intermediate Remotion props construction; they should assert on the tool result text and the returned `GeneratedSlot` shape.

**`StatVizRenderer` unit tests** — Stub `RemotionBackend.render_clip` to return a dummy path and assert that `StatVizRenderer.render` calls it with the correct composition id for each format and that `StyleBrief` fields appear in the props passed to the stub. Assert that an unsupported format raises a clear error. No Remotion subprocess required. Prior art: `NanoBananaCreator` is mocked in existing `GenerateBrollAgent` tests.

**`GenerateBrollAgent` tool dispatch tests** — Follow the existing fake-client pattern (supply a `ModelClient` stub that emits a fixed `AssistantTurn` with `render_counter`/etc. tool calls). Stub `StatVizRenderer.render` to write an empty file and return its path. Assert that `_dispatch_one` returns a `ToolResult` with `"clip saved:"` text and a `GeneratedSlot` of `kind="video"`. Assert that a raised exception from `StatVizRenderer.render` returns an error `ToolResult` and no slot. Assert that when `stat_viz_renderer=None` the render tools are absent from `_tools`.

**`RemotionBackend.render_clip` integration test** — Skipped by default unless `REMOTION_INTEGRATION=1` is set. Asserts that calling `render_clip("StatVizCounter", {...}, out_path)` produces a non-empty mp4 at the expected path. Prior art: the existing render-path integration test in the test suite.

**No snapshot tests for Remotion composition output** — The compositions are React/TypeScript components; their visual correctness is checked by running them, not by snapshotting IR. The existing IR compilation snapshots are unchanged.

## Out of Scope

- The upstream storyboarding/design agent that will supply `StyleBrief` — it is explicitly deferred; v1 uses hardcoded defaults.
- Automatic style-matching from the source video's pixels — the PRD explicitly rules this out.
- External data lookup for stats not stated in the transcript — v1 only handles claims already present in the spoken text.
- Lambda rendering — v1 uses the local `npx remotion render` path that `RemotionBackend` already shells out to.
- Any stat-viz format beyond the five listed (e.g. scatter plots, maps, treemaps) — additive later via a new composition + a new tool.
- Multi-user or SaaS concerns — single-user local-first only.
- The future specialized agents (code-animation, map, screen-recording cleanup b-roll) — same dispatch pattern but not designed here.
- Changes to the Composition schema, the IR, or the kernel — stat-viz clips are ingested as video Assets and placed by `AuthoringAgent` using existing Scene authoring; no new kernel entity is introduced.

## Further Notes

The load-bearing seam in this design is `StatVizRenderer` — it is the only module that knows both which Remotion composition id maps to which format and how `StyleBrief` merges into props. Keeping it thin and independently testable means that when the upstream design agent ships, the integration is a one-line constructor change in `build_default_pipeline`, not a refactor.

The `GenerateBrollAgent` already has `kind: Literal["image", "video"]` on `GeneratedSlot`, which anticipates this extension. The `_dispatch_parallel` parallelism model means five simultaneous `npx remotion render` processes could run concurrently. Each Remotion render is CPU and memory intensive; if contention becomes a problem in practice, adding a `max_workers` cap to the `ThreadPoolExecutor` in `_dispatch_parallel` is the targeted fix — not a change to the dispatch model.

The decision to always route stat claims to animated viz tools (never to `generate_image`) is the highest-leverage rule in this design. If it is ever relaxed (e.g. for sub-1s windows), the right place to enforce a fallback is in `GenerateBrollAgent._dispatch_one` based on `duration_s`, not in the system prompt — keeping the LLM's decision space simple.
