# `highlight-box` caption renderer

Status: ready-for-agent

## Parent

`.scratch/caption-library/PRD.md`

## What to build

The first net-new caption visual, proving the library is extensible: adding a renderer = drop a
component + register it, with no change to the core IR schema or any other layer kind.

Port the seed `HighlightCaptions` (from the reference TikTok caption template) into the project as the
**`highlight-box`** caption renderer: words split into separate wrapping highlighter boxes, each with
rotation jitter and a per-word spring pop. It renders **only** the transcript-synced word reveal —
the seed's handwritten annotation + SVG arrow are dropped (not transcript-synced, so not a caption;
out of scope for this library).

Register `highlight-box` on both sides:

- **Python:** a registry entry with its `description`, typed param schema, and defaults, so a
  `Caption` with `style: "highlight-box"` validates and compiles through the registry's `compile`.
- **TS:** the renderer component registered by id, receiving the standard renderer contract — the
  caption's `runs` (words + per-word spoken windows), the layer window, canvas + fps, and its own
  typed params. The renderer owns its phrase/box grouping, wrapping, rotation, and pop animation.

It does not read brand-kit tokens (deferred per ADR 0010). The component is the same one that will
back the gallery composition in the gallery slice.

## Acceptance criteria

- [ ] `HighlightCaptions` is ported into the project as a `highlight-box` caption renderer, word-reveal only (no annotation/arrow).
- [ ] `highlight-box` is registered on both the Python and TS sides with matching id, plus a description and param schema/defaults on the Python side.
- [ ] A `Caption` with `style: "highlight-box"` validates, compiles to a `text` layer with the right id + params, and renders the highlighter-box visual end-to-end.
- [ ] The renderer consumes the standard contract (runs + window + canvas/fps + typed params) and owns its own grouping/animation; it does not reference brand-kit tokens.
- [ ] Test: the registry compiles `highlight-box` params (defaults + overrides) to the expected IR pieces.
- [ ] Test: the TS renderer registry resolves `highlight-box` to its component.

## Blocked by

- `.scratch/caption-library/issues/01-caption-style-registry-migrate-existing.md`
