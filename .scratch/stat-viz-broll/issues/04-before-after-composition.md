Status: ready-for-agent

# 04 — Before/After composition + tool

## What to build

Add the `render_before_after` tool to `GenerateBrollAgent` and the `StatVizBeforeAfter` Remotion composition — an animated side-by-side reveal for state-change claims. Follows the identical pattern established in issue 01.

**`StatVizBeforeAfter` Remotion composition** — registered in `Root.tsx`. Props: `label_a: string`, `value_a: string`, `label_b: string`, `value_b: string`, `duration_s: number`, plus `StyleBrief` fields. All values are strings — both numeric ("3 hours", "10 minutes") and qualitative ("manual process", "automated") render as text. The animation is a sequential reveal: the "before" state appears first, then the "after" state animates in, emphasising the contrast. No count-up animation — that belongs to `render_counter`.

**`render_before_after` tool on `GenerateBrollAgent`** — tight schema:

```
render_before_after(slot, label_a, value_a, label_b, value_b, duration_s)
```

**`StatVizRenderer`** — add `"before_after"` as a supported format mapping to `"StatVizBeforeAfter"`.

## Acceptance criteria

- [ ] `StatVizRenderer.render("before_after", data, style, out_path)` calls `RemotionBackend.render_clip` with composition id `"StatVizBeforeAfter"` and correct merged props
- [ ] Both `value_a` and `value_b` are passed as strings — no numeric coercion
- [ ] A qualitative pair (e.g. `value_a="manual process"`, `value_b="automated"`) is accepted without error
- [ ] A stubbed `render_before_after` tool call on `GenerateBrollAgent` returns a `GeneratedSlot(kind="video")`
- [ ] `render_before_after` is absent from the tool list when `stat_viz_renderer=None`

## Blocked by

- 01 — Counter tracer bullet
