"""Two-tier validation: local (hard errors) + global (reported warnings) + the submit gate.

The Validator encodes CONTEXT.md's coverage rules and the project's split between *structural
illegality* and *authoring smell* (ADR 0004):

- **Local** validation produces hard ``LocalError``s -- conditions a Composition must never
  contain (overlapping scenes, a Reference into a region the Layout does not expose, a dangling
  Asset reference, a Caption outside the voiceover, an out-of-bounds scene, a bad overlay target).
  Any local error blocks the submit gate.
- **Global** validation produces reported ``GlobalWarning``s -- legal-but-suspicious conditions,
  chiefly **gaps** between scenes, which render as black with the voiceover continuing. Warnings
  are informational and never block.

The Composition carries no duration of its own; the voiceover (master clock, ADR 0005) sets it, so
callers pass the probed ``duration`` in -- the same fact ``compile_ir`` consumes. This module is
pure kernel: it reads the Phase 1 contract types and depends on no service or backend (ADR 0003).
The ``full``/``split-h`` region map is hard-coded here; Phase 5's layout registry replaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from videogen.kernel.composition import (
    Composition,
    LayoutName,
    Overlay,
    RegionName,
)

# Which Regions each built-in Layout exposes (CONTEXT.md). Phase 5's registry supersedes this.
_LAYOUT_REGIONS: dict[LayoutName, frozenset[RegionName]] = {
    LayoutName.full: frozenset({RegionName.full}),
    LayoutName.split_h: frozenset({RegionName.top, RegionName.bottom}),
}


class ErrorCode(StrEnum):
    """Stable codes for local hard errors; callers and tests key off these, not the messages."""

    SCENE_OVERLAP = "scene_overlap"
    SCENE_TIME_ORDER = "scene_time_order"
    SCENE_OUT_OF_BOUNDS = "scene_out_of_bounds"
    REGION_NOT_IN_LAYOUT = "region_not_in_layout"
    TARGET_REGION_INVALID = "target_region_invalid"
    DANGLING_ASSET = "dangling_asset"
    CAPTION_TIME_ORDER = "caption_time_order"
    CAPTION_OUT_OF_BOUNDS = "caption_out_of_bounds"
    OVERLAY_TIME_ORDER = "overlay_time_order"
    # Builder op-precondition failures: the op cannot apply at all (not document invalidity), but
    # they are surfaced as errors so the authoring loop stays self-correcting rather than raising.
    UNKNOWN_SCENE = "unknown_scene"
    UNKNOWN_CAPTION = "unknown_caption"
    DUPLICATE_SCENE_ID = "duplicate_scene_id"


class WarningCode(StrEnum):
    """Stable codes for global reported warnings (gaps); never block the submit gate."""

    LEADING_GAP = "leading_gap"
    SCENE_GAP = "scene_gap"
    TRAILING_GAP = "trailing_gap"
    NO_SCENES = "no_scenes"


@dataclass(frozen=True)
class LocalError:
    """A hard error localized to the offending entity; blocks render submission."""

    code: ErrorCode
    message: str
    entity_ref: str | None = None


@dataclass(frozen=True)
class GlobalWarning:
    """A reported, non-blocking warning, optionally carrying the suspicious ``(start, end)``."""

    code: WarningCode
    message: str
    span: tuple[float, float] | None = None


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of validating a Composition (or, from the Builder, a single mutation).

    ``ok`` reflects *local errors only*: warnings are informational and never make a result not-ok,
    matching the submit gate (warnings do not block).
    """

    errors: tuple[LocalError, ...] = ()
    warnings: tuple[GlobalWarning, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """Half-open overlap: a touching boundary (a.end == b.start) is a clean cut, not an overlap."""
    return a_start < b_end and b_start < a_end


def validate_local(composition: Composition, *, duration: float) -> list[LocalError]:
    """Run the local pass: every condition a Composition must never contain (hard errors)."""
    errors: list[LocalError] = []
    assets = composition.assets

    if composition.voiceover.asset not in assets:
        errors.append(
            LocalError(
                ErrorCode.DANGLING_ASSET,
                f"voiceover references undeclared asset '{composition.voiceover.asset}'",
                "voiceover",
            )
        )

    for scene in composition.scenes:
        if scene.start >= scene.end:
            errors.append(
                LocalError(
                    ErrorCode.SCENE_TIME_ORDER,
                    f"scene '{scene.id}' has start {scene.start} >= end {scene.end}",
                    scene.id,
                )
            )
        if scene.end > duration:
            errors.append(
                LocalError(
                    ErrorCode.SCENE_OUT_OF_BOUNDS,
                    f"scene '{scene.id}' end {scene.end} exceeds voiceover duration {duration}",
                    scene.id,
                )
            )
        exposed = _LAYOUT_REGIONS.get(scene.layout, frozenset())
        for region, ref in scene.regions.items():
            if region not in exposed:
                errors.append(
                    LocalError(
                        ErrorCode.REGION_NOT_IN_LAYOUT,
                        f"scene '{scene.id}' fills region '{region.value}' not exposed by layout "
                        f"'{scene.layout.value}'",
                        scene.id,
                    )
                )
            if ref.asset not in assets:
                errors.append(
                    LocalError(
                        ErrorCode.DANGLING_ASSET,
                        f"scene '{scene.id}' references undeclared asset '{ref.asset}'",
                        scene.id,
                    )
                )

    # Scene non-overlap on the base layer. Sweep by start time tracking the running max end; any
    # scene starting before that maximum overlaps an earlier one (catches containment, not just
    # adjacent pairs).
    running_end = 0.0
    running_id: str | None = None
    for scene in sorted(composition.scenes, key=lambda s: (s.start, s.end)):
        if running_id is not None and scene.start < running_end:
            errors.append(
                LocalError(
                    ErrorCode.SCENE_OVERLAP,
                    f"scene '{scene.id}' overlaps scene '{running_id}' on the base layer",
                    scene.id,
                )
            )
        if scene.end > running_end:
            running_end, running_id = scene.end, scene.id

    for index, caption in enumerate(composition.captions):
        entity = f"caption[{index}]"
        if caption.start >= caption.end:
            errors.append(
                LocalError(
                    ErrorCode.CAPTION_TIME_ORDER,
                    f"caption {index} has start {caption.start} >= end {caption.end}",
                    entity,
                )
            )
        if caption.start < 0 or caption.end > duration:
            errors.append(
                LocalError(
                    ErrorCode.CAPTION_OUT_OF_BOUNDS,
                    f"caption {index} span ({caption.start}, {caption.end}) falls outside the "
                    f"voiceover [0, {duration}]",
                    entity,
                )
            )

    for index, overlay in enumerate(composition.overlays):
        entity = f"overlay[{index}]"
        if overlay.start >= overlay.end:
            errors.append(
                LocalError(
                    ErrorCode.OVERLAY_TIME_ORDER,
                    f"overlay {index} has start {overlay.start} >= end {overlay.end}",
                    entity,
                )
            )
        if overlay.target != RegionName.full and not _target_exposed(composition, overlay):
            errors.append(
                LocalError(
                    ErrorCode.TARGET_REGION_INVALID,
                    f"overlay {index} targets region '{overlay.target.value}', not exposed by any "
                    f"scene active during its span",
                    entity,
                )
            )

    return errors


def _target_exposed(composition: Composition, overlay: Overlay) -> bool:
    """A non-``full`` target is valid only while a scene exposing it is active (CONTEXT.md).

    Conservative seam for Phase 4: true iff at least one scene overlapping the overlay's span
    exposes the target region. Overlay *types* and the full per-instant check arrive in Phase 6.
    """
    for scene in composition.scenes:
        if _overlaps(overlay.start, overlay.end, scene.start, scene.end) and (
            overlay.target in _LAYOUT_REGIONS.get(scene.layout, frozenset())
        ):
            return True
    return False


def validate_global(composition: Composition, *, duration: float) -> list[GlobalWarning]:
    """Run the global pass: legal-but-suspicious conditions (gaps), reported as warnings."""
    warnings: list[GlobalWarning] = []

    if not composition.scenes:
        if duration > 0:
            warnings.append(
                GlobalWarning(
                    WarningCode.NO_SCENES,
                    "composition has no scenes; the whole duration renders black",
                    (0.0, duration),
                )
            )
        return warnings

    # Sweep scenes in time order, tracking covered extent. A scene starting beyond the cursor leaves
    # a gap: at the very start it is a leading gap, otherwise an inter-scene gap. (Overlaps, if any,
    # are reported by the local pass; here ``max`` keeps the cursor monotonic.)
    cursor = 0.0
    for scene in sorted(composition.scenes, key=lambda s: (s.start, s.end)):
        if scene.start > cursor:
            code = WarningCode.LEADING_GAP if cursor == 0.0 else WarningCode.SCENE_GAP
            where = "before the first scene" if cursor == 0.0 else "between scenes"
            warnings.append(
                GlobalWarning(code, f"gap {where}: renders black", (cursor, scene.start))
            )
        cursor = max(cursor, scene.end)

    if cursor < duration:
        warnings.append(
            GlobalWarning(
                WarningCode.TRAILING_GAP,
                "trailing gap after the last scene: a black tail while the voiceover continues",
                (cursor, duration),
            )
        )

    return warnings


def validate(composition: Composition, *, duration: float) -> ValidationResult:
    """Run both tiers and return the composed result (local errors + global warnings)."""
    return ValidationResult(
        errors=tuple(validate_local(composition, duration=duration)),
        warnings=tuple(validate_global(composition, duration=duration)),
    )


def can_submit_render(composition: Composition, *, duration: float) -> bool:
    """The submit gate: true iff the local pass yields no errors. Warnings never block (ADR 0003).

    RenderService (Phase 7) and the authoring agent (Phase 8) consult this same predicate so the
    rule lives in exactly one place.
    """
    return not validate_local(composition, duration=duration)
