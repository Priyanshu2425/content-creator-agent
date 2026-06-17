Status: ready-for-agent

# 03 — Gauge composition + tool

## What to build

Add the `render_gauge` tool to `GenerateBrollAgent` and the `StatVizGauge` Remotion composition — an animated progress ring. Follows the identical pattern established in issue 01.

**`StatVizGauge` Remotion composition** — registered in `Root.tsx`. Props: `value: number`, `max: number`, `label: string`, `unit: string`, `duration_s: number`, plus `StyleBrief` fields. Animates a progress ring filling from 0 to `value / max`. `max` is arbitrary — not constrained to 100 — so claims like "raised $3M of a $10M goal" render correctly. Displays the raw `value` and `unit` as text in the centre of the ring.

**`render_gauge` tool on `GenerateBrollAgent`** — tight schema:

```
render_gauge(slot, value, max, unit, label, duration_s)
```

**`StatVizRenderer`** — add `"gauge"` as a supported format mapping to `"StatVizGauge"`.

## Acceptance criteria

- [ ] `StatVizRenderer.render("gauge", data, style, out_path)` calls `RemotionBackend.render_clip` with composition id `"StatVizGauge"` and correct merged props
- [ ] `max` is passed through to the composition and used to compute the fill fraction (not hardcoded to 100)
- [ ] A stubbed `render_gauge` tool call on `GenerateBrollAgent` returns a `GeneratedSlot(kind="video")`
- [ ] `render_gauge` is absent from the tool list when `stat_viz_renderer=None`

## Blocked by

- 01 — Counter tracer bullet
