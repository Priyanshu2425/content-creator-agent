"""The chain's deterministic post-Composer reconcile step (ADR 0013).

The Composer decides *placement* (which asset, what span, what layout). Two things it should NOT be
asked to do are pure deterministic functions of ground truth, so they live here instead -- the mirror
image of the pre-Composer ``prep`` step:

1. **Base captions** -- the ``captions`` track is filled in bulk from the transcript word-timings in
   the brand kit's default caption style (e.g. ``tiktok``). A model emitting every word-timed caption
   would be voluminous and drift; this is a lookup, so it is code.
2. **Animate stills** -- a still image left motionless on screen past ``STATIC_IMAGE_MAX_SECONDS``
   reads as dead on a feed. Each such still gets a slow Ken-Burns zoom over its whole span (it is
   *animated*, not *shortened* -- the master clock is the voiceover, so spans are fixed). This clears
   the kernel ``STATIC_IMAGE_TOO_LONG`` warning by giving the still motion.

Pure and reusable: a fake Composition + transcript exercise it with no model or backend.
"""

from __future__ import annotations

from videogen.kernel.builder import Builder, TranscriptLike
from videogen.kernel.composition import AssetType, Composition, Hook, ZoomOverlay
from videogen.kernel.validator import STATIC_IMAGE_MAX_SECONDS, _has_motion_cover


def reconcile(
    composition: Composition,
    *,
    transcript: TranscriptLike,
    duration: float,
    caption_style: str = "tiktok",
    static_max_seconds: float = STATIC_IMAGE_MAX_SECONDS,
    zoom_to: float = 1.12,
    hook: Hook | None = None,
) -> Composition:
    """Apply the deterministic post-Composer reconciliation: the kernel-level hook (the text-hook
    worker's output), base captions (suppressed under the hook window), and animate stills."""
    composition = _fill_base_captions(composition, transcript, duration, caption_style)
    if hook is not None:
        composition = _apply_hook(composition, hook)
    composition = _animate_long_stills(composition, static_max_seconds, zoom_to)
    return composition


def _apply_hook(composition: Composition, hook: Hook) -> Composition:
    """Set the kernel-level hook and suppress base captions fully inside its window (ADR 0013).

    The hook owns the opening: captions that end within ``[0, hook.duration]`` are dropped (their words
    are covered by the hook); a caption straddling the boundary stays, so captions resume in sync the
    instant the hook ends."""
    kept = [c for c in composition.captions if c.end > hook.duration]
    return composition.model_copy(update={"hook": hook, "captions": kept})


def _fill_base_captions(
    composition: Composition, transcript: TranscriptLike, duration: float, style: str
) -> Composition:
    """Populate the captions track from the transcript in ``style`` -- unless the Composer already
    authored captions (don't double-fill). Reuses the Builder's karaoke line grouping."""
    if composition.captions:
        return composition
    builder = Builder(composition, duration=duration)
    result = builder.add_captions_from_transcript(transcript, style=style)
    return builder.composition if result.ok else composition


def _animate_long_stills(
    composition: Composition, static_max_seconds: float, zoom_to: float
) -> Composition:
    """Add a slow zoom over every still-image scene held longer than ``static_max_seconds`` that has
    no motion cover yet -- so a held still is alive, not dead. Spans are untouched."""
    extra: list[ZoomOverlay] = []
    for scene in composition.scenes:
        if scene.end - scene.start <= static_max_seconds:
            continue
        for region, ref in scene.regions.items():
            asset = composition.assets.get(ref.asset)
            if asset is None or asset.type is not AssetType.image:
                continue
            if _has_motion_cover(composition, scene, region):
                continue
            extra.append(
                ZoomOverlay(
                    start=scene.start,
                    end=scene.end,
                    target=region,
                    from_scale=1.0,
                    to_scale=zoom_to,
                )
            )
    if not extra:
        return composition
    return composition.model_copy(update={"overlays": [*composition.overlays, *extra]})
