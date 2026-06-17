Status: ready-for-agent

# 05 — Ratio composition + tool

## What to build

Add the `render_ratio` tool to `GenerateBrollAgent` and the `StatVizRatio` Remotion composition — an animated ratio/icon-fill for "X in N" and "X out of Y" claims. Follows the identical pattern established in issue 01.

**`StatVizRatio` Remotion composition** — registered in `Root.tsx`. Props: `numerator: number`, `denominator: number`, `label: string`, `duration_s: number`, plus `StyleBrief` fields. Renders a row of `denominator` icons; `numerator` of them fill in with the accent colour, the rest remain in a muted state. Animates the fill sequentially over `duration_s`. The `label` text (e.g. "churn within 90 days") appears below the icon row.

**`render_ratio` tool on `GenerateBrollAgent`** — tight schema:

```
render_ratio(slot, numerator, denominator, label, duration_s)
```

**`StatVizRenderer`** — add `"ratio"` as a supported format mapping to `"StatVizRatio"`.

## Acceptance criteria

- [ ] `StatVizRenderer.render("ratio", data, style, out_path)` calls `RemotionBackend.render_clip` with composition id `"StatVizRatio"` and correct merged props
- [ ] `numerator` and `denominator` are passed through correctly; the composition renders `denominator` icons with `numerator` filled
- [ ] A stubbed `render_ratio` tool call on `GenerateBrollAgent` returns a `GeneratedSlot(kind="video")`
- [ ] `render_ratio` is absent from the tool list when `stat_viz_renderer=None`

## Blocked by

- 01 — Counter tracer bullet
