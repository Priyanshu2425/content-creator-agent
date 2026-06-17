Status: ready-for-agent

# 06 — System prompt routing: stat claims always use animated viz

## What to build

Update `GenerateBrollAgent`'s system prompt so that "Data / statistic" claim types always route to the five animated viz tools — `generate_image` is never called for a numerical stat.

**Taxonomy table update** — the existing claim-type decision table maps "Data / statistic" to "stat card" (i.e. `generate_image`). Replace that row with a routing rule pointing to the five `render_*` tools. The new sub-type decision table:

| Stat sub-type | Spoken trigger example | Tool |
|---|---|---|
| Single number / percentage | "revenue grew 40%", "10x faster" | `render_counter` |
| Two-value comparison | "80% vs 20%", "A outperforms B" | `render_bar` |
| Progress toward a goal | "raised $3M of $10M" | `render_gauge` |
| State change (numeric or qualitative) | "3 hours → 10 minutes", "manual → automated" | `render_before_after` |
| Fraction of a whole | "1 in 3 users", "2 out of 5" | `render_ratio` |

**GENERATEBROLL PLAN format update** — for stat slots, replace the "Image approach" field with "Animation approach" (e.g. `render_counter`, `render_bar`, etc.) so the plan narration records the format choice and its justification.

**No change to non-stat claim types** — emotion, UI, location, social proof, and all other claim types continue to use `generate_image` unchanged.

## Acceptance criteria

- [ ] The system prompt's claim-type taxonomy no longer maps any stat sub-type to `generate_image`
- [ ] The sub-type decision table covering all five formats is present and unambiguous
- [ ] The GENERATEBROLL PLAN output format uses "Animation approach" for stat slots
- [ ] Non-stat claim types (emotion, UI, location, social proof, etc.) still map to `generate_image` in the taxonomy
- [ ] A manual inspection of one agent run on a real transcript confirms stat moments call `render_*` tools and not `generate_image`

## Blocked by

- 01 — Counter tracer bullet
- 02 — Bar composition + tool
- 03 — Gauge composition + tool
- 04 — Before/After composition + tool
- 05 — Ratio composition + tool
