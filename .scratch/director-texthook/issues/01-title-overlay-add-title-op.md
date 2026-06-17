# `title` overlay type + `add_title` Builder op

Status: ready-for-agent

## Parent

`.scratch/director-texthook/PRD.md` (Phase 2)

## What to build

Add kernel support for placing a static text headline, distinct from captions. Introduce a new
**additive `title` overlay** type — registered like `zoom`/`pan`/`insert`, with its own params schema
(text, region/placement, brand-kit style reference), validated by the existing two-phase
envelope + params path, painted in the z stack. Add a new **`add_title`** Builder op (and advertise
it on the tool surface) that places one title overlay. `compile_ir` maps a `title` overlay to the
existing IR `TextLayer`, so the Remotion backend renders it with no new node kind (ADR 0002 intact).
This slice is verifiable on its own with a manually-specified title — the TextHookAgent comes next.

## Acceptance criteria

- [ ] A `title` overlay is registered and validated; malformed params are rejected via the params
      schema; envelope fields validated.
- [ ] `add_title` places one title overlay as a single validated Builder op.
- [ ] A composition with a `title` overlay compiles to a `TextLayer` and renders a static headline
      (no new IR/backend node kind).
- [ ] The title is additive (painted, participates in z) and distinct from the captions track.
- [ ] Snapshot coverage pins the title → `TextLayer` compilation; kernel validation tests cover accept
      and reject cases.

## Blocked by

- `.scratch/director-restructure/issues/01-rename-authoring-to-director.md`
