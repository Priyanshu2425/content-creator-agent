# Agent reads registry + feature/base caption selection

Status: ready-for-agent

## Parent

`.scratch/caption-library/PRD.md`

## What to build

Wire the caption library into the authoring agents so caption styles are chosen from the registry
rather than a hardcoded enum, and so the two caption roles are honored.

- **Discovery:** the creative-direction agent's allowed caption styles come from the registry's
  `list()` (id + description), not the `CaptionStyle` enum. Adding a renderer automatically makes it
  selectable. Update the agent tooling/prompts that previously derived their options from the enum.
- **Feature captions:** the creative-direction agent can set a non-default style on specific captions
  (a hook or emphasis moment), making them stand apart from base captions. Same `Caption` entity —
  the difference is the deliberately chosen style.
- **Base captions:** the auto-populated transcript captions resolve to the brand kit's **default
  caption style** id. (The transcription→captions population itself already exists and is not changed
  here; this slice ensures the default style is a registry id and is applied.)

A style the agent selects must be a registered id; an unknown id is rejected/warned exactly as the
kernel validates it.

## Acceptance criteria

- [ ] The creative-direction agent's caption-style options are sourced from `registry.list()` (id + description); no remaining dependency on the closed `CaptionStyle` enum in agent tooling.
- [ ] A new renderer registered after this slice is automatically selectable by the agent with no agent-code change.
- [ ] The agent can set a non-default (feature) style on a specific caption; base captions take the brand kit's default caption style id.
- [ ] An agent-selected style that is not registered is rejected/warned per the kernel's validation rules.
- [ ] Test: agent style options reflect the registered set; selecting a registered id produces a caption with that style, an unknown id is rejected.

## Blocked by

- `.scratch/caption-library/issues/01-caption-style-registry-migrate-existing.md`
- `.scratch/caption-library/issues/02-highlight-box-renderer.md`
