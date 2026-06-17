# SFXAgent worker + Director event-timeline + `dispatch_sfx`

Status: ready-for-agent

## Parent

`.scratch/director-sfx/PRD.md` (Phase 3)

## What to build

Recast `AudioDeciderAgent` as the **SFXAgent** worker, dispatched in-loop via `dispatch_sfx`
(ADR 0008), and make it the single SFX authority (ADR 0009). Add a pure **event-timeline builder**
the Director runs over the assembled composition to produce typed events (`hook`, `scene_change`,
`reveal`, `graphic_pop`, `caption_emphasis`, `list_item`, `cta`) — the worker receives these rather
than inferring them. The Director dispatches the worker (steered late, after visuals are placed) with
the event timeline + brand-kit sfx palette + density budget; the worker maps event types to palette
keys deterministically, keeps only high-impact `reveal`/`caption_emphasis` candidates, enforces the
budget locally (min gap, max-per-10s, no overlap), logs what it chose not to sound, and returns a
placement proposal — certifying nothing. The Director applies accepted placements via the existing
`scene.audio` path (cut-bound v1) using the three real palette sounds. End result: a video gets
restrained, on-meaning SFX with no whoosh double-fire.

## Acceptance criteria

- [ ] The pure event-timeline builder turns a composition into the typed event stream; micro
      jump-cuts are excluded.
- [ ] The Director dispatches `dispatch_sfx` (late) with the event timeline + palette + density budget.
- [ ] The worker maps events → palette keys, drops low-impact candidates, enforces the budget (gaps ≥
      min, ≤ max per 10s, no overlap), and places nothing for an off-kit event (with a note).
- [ ] Placements are applied via `scene.audio` and render through the audio IR node; v1 palette =
      `click`/`whoosh`/`dramatic_whoosh`.
- [ ] No double-fire on a whoosh-transition cut (SFXAgent is the sole authority).
- [ ] Unit tests cover the event-timeline builder; a fake-`ModelClient` test covers mapping, emphasis
      pass, and budget enforcement.

## Blocked by

- `.scratch/director-restructure/issues/03-in-loop-dispatch-broll-worker.md`
- `.scratch/director-sfx/issues/01-decouple-whoosh-transition-sound.md`
