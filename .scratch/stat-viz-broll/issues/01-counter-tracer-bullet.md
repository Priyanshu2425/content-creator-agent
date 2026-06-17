Status: ready-for-agent

# 01 — Counter tracer bullet

## What to build

Wire the entire stat-viz pipeline end-to-end for the `render_counter` format. This slice establishes every foundational layer the remaining four compositions will reuse.

**`StyleBrief` data class** — `background`, `primary`, `accent`, `font_family` fields. A module-level `DEFAULT_STYLE_BRIEF` constant supplies hardcoded sensible defaults (dark background, white primary, orange accent, Inter font). This is the seam the future upstream design agent will plug into.

**`RemotionBackend.render_clip(composition_id, props, out_path)`** — new method alongside `render_video` and `render_still`. Shells out to `npx remotion render <entry> <composition_id> <out_path> --props <json>` where `props` is a raw dict (not an IR). Does not touch `render_video` or `render_still`.

**`StatVizRenderer`** — new class with a single public method:

```
render(format, data, style: StyleBrief, out_path, fps=30) -> Path
```

Maps `format` → Remotion composition id, merges `data` and `style` into a props dict, delegates to `RemotionBackend.render_clip`. For this slice, only `"counter"` is a valid format; others raise a clear error.

**`StatVizCounter` Remotion composition** — registered in the existing project's `Root.tsx` alongside `Main`. Accepts props: `value: number`, `unit: string`, `label: string`, `duration_s: number`, plus `StyleBrief` fields (`background`, `primary`, `accent`, `font_family`). Animates a count-up from 0 to `value` over `duration_s` seconds, displaying `label` and `unit`.

**`render_counter` tool on `GenerateBrollAgent`** — tight schema, no cross-format optional fields:

```
render_counter(slot, value, unit, label, duration_s)
```

`GenerateBrollAgent` constructor gains `stat_viz_renderer: StatVizRenderer | None = None`. When `None`, the render tools are absent from the tool list entirely (image-only mode preserved). `_dispatch_one` gains a `render_counter` branch: calls `StatVizRenderer.render("counter", ...)`, saves to `dest/slot_{n}_{uuid}.mp4`, returns `GeneratedSlot(kind="video", ...)`. A raised exception returns an error `ToolResult` with no slot — same failure behaviour as `generate_image`.

Aspect ratio is not a tool parameter — the Python layer derives it from the pipeline's `platform` setting (9:16 for Instagram/TikTok). `duration_s` from the tool call is clamped to the slot's window duration in the dispatch layer before being passed to `StatVizRenderer`.

## Acceptance criteria

- [ ] `RemotionBackend.render_clip("StatVizCounter", {...}, out_path)` produces a non-empty mp4 at the expected path (verified by integration test, skipped unless `REMOTION_INTEGRATION=1`)
- [ ] `StatVizRenderer.render("counter", data, style, out_path)` calls `RemotionBackend.render_clip` with the correct composition id and merged props (verified by unit test with stubbed backend)
- [ ] `StatVizRenderer.render` raises a clear error for unsupported formats
- [ ] `GenerateBrollAgent` with `stat_viz_renderer=None` has `render_counter` absent from its tool list
- [ ] A stubbed `render_counter` tool call returns a `GeneratedSlot(kind="video")` with the clip path
- [ ] A `render_counter` call where `StatVizRenderer.render` raises returns an error `ToolResult` and no slot
- [ ] `StyleBrief` fields appear in the props passed to `RemotionBackend.render_clip`
- [ ] `DEFAULT_STYLE_BRIEF` is used when no `StyleBrief` is explicitly supplied

## Blocked by

None — can start immediately.
