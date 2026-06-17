Status: ready-for-agent

# 02 — Bar composition + tool

## What to build

Add the `render_bar` tool to `GenerateBrollAgent` and the `StatVizBar` Remotion composition — a two-value animated bar comparison. Follows the identical pattern established in issue 01.

**`StatVizBar` Remotion composition** — registered in `Root.tsx`. Props: `label_a: string`, `value_a: number`, `label_b: string`, `value_b: number`, `unit: string`, `duration_s: number`, plus `StyleBrief` fields. Animates two bars filling in from 0 to their respective values, with labels and a shared unit. Suitable for "Company A: 80%, Company B: 20%" and similar two-value comparisons.

**`render_bar` tool on `GenerateBrollAgent`** — tight schema:

```
render_bar(slot, label_a, value_a, label_b, value_b, unit, duration_s)
```

**`StatVizRenderer`** — add `"bar"` as a supported format mapping to `"StatVizBar"`.

## Acceptance criteria

- [ ] `StatVizRenderer.render("bar", data, style, out_path)` calls `RemotionBackend.render_clip` with composition id `"StatVizBar"` and correct merged props
- [ ] A stubbed `render_bar` tool call on `GenerateBrollAgent` returns a `GeneratedSlot(kind="video")`
- [ ] Both `value_a` and `value_b` appear correctly in the props passed to the composition
- [ ] `render_bar` is absent from the tool list when `stat_viz_renderer=None`

## Blocked by

- 01 — Counter tracer bullet
