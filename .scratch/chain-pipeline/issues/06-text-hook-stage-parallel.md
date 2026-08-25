# Text-hook stage (parallel, concept-consuming)

Status: ready-for-agent

## Parent

`.scratch/chain-pipeline/PRD.md` — Chain pipeline.

## What to build

Add the **text-hook** worker as a third parallel stage alongside broll and motion-graphics (all after
creative direction). The text hook consumes the **creative concept** (not generated assets), so it
parallelizes with the generators. Its `HookProposal` flows in the typed bundle to the Composer, which
places the opening headline as an additive `title` overlay on the first ~1–3s. A text-hook failure
**degrades** — the run continues with no opening overlay.

## Acceptance criteria

- [ ] Text hook runs concurrently with broll and motion-graphics.
- [ ] The hook is built from the creative concept, not from generated assets.
- [ ] The Composer places the hook as a `title` overlay over the opening seconds.
- [ ] A text-hook failure leaves the run intact with no opening overlay.
- [ ] A test asserts the hook reaches the Composer and a failure degrades cleanly.

## Blocked by

- `04-creative-direction-to-composer-typed-passing.md`
