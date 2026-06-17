# Brand kit from an optional brand profile, superseding StyleBrief

Status: ready-for-agent

## Parent

`.scratch/director-restructure/PRD.md` (Phase 1)

## What to build

Add a new optional **`brand_profile`** pipeline input and a **BrandKit builder** deep module that
loads it when present, otherwise derives a sensible brand kit from the brief, then **locks** it for
the whole video. The Director holds the locked kit as the single source of truth for design language
and injects it to workers as compact tokens. v1 kit tokens: colors (bg/primary/accent), font, caption
style (mapped to the fixed `pill`/`word-bold`/`kinetic` set), sfx palette + density budget (carried
for Phase 3), frame meta (from `MediaManifest`), and safe zones. `StyleBrief` is re-expressed as a
projection of the brand kit, and `DEFAULT_STYLE_BRIEF` stops being the source of truth — so stat-viz
clips render in the kit's colors/font.

## Acceptance criteria

- [ ] A supplied `brand_profile` is loaded and locked; with none supplied, a kit is derived from the
      brief and locked.
- [ ] Caption style resolves to one of the fixed `pill`/`word-bold`/`kinetic` set; safe zones present.
- [ ] `StyleBrief` is produced as a projection of the brand kit; rendering a video with a brand profile
      shows its colors/font on stat-viz clips.
- [ ] `DEFAULT_STYLE_BRIEF` is no longer the source of truth.
- [ ] Unit tests cover the BrandKit builder (derive-from-brief, load-profile, caption-style mapping,
      safe zones present) per the PRD test scope.

## Blocked by

- `.scratch/director-restructure/issues/01-rename-authoring-to-director.md`
