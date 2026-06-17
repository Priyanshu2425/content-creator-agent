"""Pacing reconciler: the Director's behavioral pacing pass (restructure/05, ADR 0008).

Pacing is an emergent, whole-timeline property; the Director is the only agent that sees every layer,
so it reconciles pacing itself rather than the kernel enforcing it (the validator stays about
correctness). This module is the pure core:

- ``analyze_pacing`` reads the composition and reports **static gaps** (stretches with no change
  beyond ``max_static_gap``), **collisions** (two competing additive overlays on screen at once),
  **safe-zone violations** (inserts anchored into the top/bottom UI bands), and **hook-window
  intrusions** (a competing overlay inside the reserved opening).
- ``fill_static_gaps`` acts on the gaps with content-free zoom punch-ins (the doc's "punch-ins are
  content-free, add them directly"), spacing them so no sub-stretch exceeds the budget.

Everything here is deterministic and unit-testable; the Director runs it as a behavioral pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from videogen.agent.brand_kit import SafeZones
from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    AdditiveOverlay,
    Anchor,
    Composition,
    InsertOverlay,
    RegionName,
    ZoomOverlay,
)

_TOP_ANCHORS = {Anchor.top_left, Anchor.top_right}
_BOTTOM_ANCHORS = {Anchor.bottom_left, Anchor.bottom_right}


@dataclass(frozen=True)
class PacingBudget:
    """The pacing limits the Director reconciles against (tuned by goal upstream)."""

    target_change_interval: tuple[float, float] = (2.0, 4.0)
    max_static_gap: float = 4.0
    min_change_interval: float = 1.5
    hook_window: tuple[float, float] = (0.0, 3.0)


@dataclass(frozen=True)
class Gap:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Collision:
    """Two competing additive overlays painted at once over ``[start, end]``."""

    a_ref: str
    b_ref: str
    start: float
    end: float


@dataclass(frozen=True)
class SafeZoneViolation:
    ref: str
    edge: str  # "top" | "bottom"


@dataclass(frozen=True)
class HookWindowIntrusion:
    ref: str
    start: float
    end: float


@dataclass(frozen=True)
class PacingReport:
    gaps: tuple[Gap, ...] = ()
    collisions: tuple[Collision, ...] = ()
    safe_zone_violations: tuple[SafeZoneViolation, ...] = ()
    hook_window_intrusions: tuple[HookWindowIntrusion, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not (
            self.gaps
            or self.collisions
            or self.safe_zone_violations
            or self.hook_window_intrusions
        )


def analyze_pacing(
    composition: Composition,
    *,
    duration: float,
    budget: PacingBudget | None = None,
    safe_zones: SafeZones | None = None,
) -> PacingReport:
    """Inspect the composition and report pacing problems the Director should act on."""
    budget = budget or PacingBudget()
    safe_zones = safe_zones or SafeZones()
    return PacingReport(
        gaps=_find_gaps(composition, duration, budget),
        collisions=_find_collisions(composition),
        safe_zone_violations=_find_safe_zone_violations(composition, safe_zones),
        hook_window_intrusions=_find_hook_intrusions(composition, budget.hook_window),
    )


def fill_static_gaps(
    builder: Builder,
    *,
    duration: float,
    budget: PacingBudget | None = None,
    punch_in_scale: float = 1.1,
) -> int:
    """Fill each static gap with content-free zoom punch-ins and return how many were added.

    Punch-ins are spaced at ~80% of ``max_static_gap`` so the gap is broken into sub-stretches that
    each stay within budget. A punch-in is a short zoom on the full frame -- the safest change to add
    without re-invoking a worker. Each placement is a validated Builder op; one that rejects is
    skipped (de-duplication: a punch-in landing on an existing change is simply not added).
    """
    budget = budget or PacingBudget()
    report = analyze_pacing(builder.composition, duration=duration, budget=budget)
    step = max(budget.max_static_gap * 0.8, budget.min_change_interval)
    span = min(budget.target_change_interval[0], step)
    added = 0
    for gap in report.gaps:
        t = round(gap.start + step, 3)
        while t < gap.end - 1e-6:
            end = round(min(t + span, gap.end), 3)
            result = builder.add_overlay(
                ZoomOverlay(
                    start=t, end=end, target=RegionName.full, from_scale=1.0, to_scale=punch_in_scale
                )
            )
            if result.ok:
                added += 1
            t = round(t + step, 3)
    return added


def _change_timestamps(composition: Composition) -> list[float]:
    """Every moment the frame changes: scene boundaries, overlay starts, caption pops."""
    changes: set[float] = set()
    for scene in composition.scenes:
        changes.add(round(scene.start, 3))
    for overlay in composition.overlays:
        changes.add(round(overlay.start, 3))
    for caption in composition.captions:
        changes.add(round(caption.start, 3))
    return sorted(changes)


def _find_gaps(composition: Composition, duration: float, budget: PacingBudget) -> tuple[Gap, ...]:
    boundaries = sorted({0.0, *(_change_timestamps(composition)), round(duration, 3)})
    gaps: list[Gap] = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b - a > budget.max_static_gap:
            gaps.append(Gap(start=a, end=b))
    return tuple(gaps)


def _additive(composition: Composition) -> list[AdditiveOverlay]:
    return [o for o in composition.overlays if isinstance(o, AdditiveOverlay)]


def _overlay_ref(overlay: AdditiveOverlay) -> str:
    asset = getattr(overlay, "asset", None)
    return f"{overlay.type}@{overlay.start:.1f}" + (f"({asset})" if asset else "")


def _find_collisions(composition: Composition) -> tuple[Collision, ...]:
    additive = _additive(composition)
    collisions: list[Collision] = []
    for i, a in enumerate(additive):
        for b in additive[i + 1 :]:
            start = max(a.start, b.start)
            end = min(a.end, b.end)
            if start < end:  # genuine overlap
                collisions.append(
                    Collision(_overlay_ref(a), _overlay_ref(b), round(start, 3), round(end, 3))
                )
    return tuple(collisions)


def _find_safe_zone_violations(
    composition: Composition, safe_zones: SafeZones
) -> tuple[SafeZoneViolation, ...]:
    out: list[SafeZoneViolation] = []
    for overlay in composition.overlays:
        if not isinstance(overlay, InsertOverlay):
            continue
        if safe_zones.top_pct > 0 and overlay.anchor in _TOP_ANCHORS:
            out.append(SafeZoneViolation(_overlay_ref(overlay), "top"))
        elif safe_zones.bottom_pct > 0 and overlay.anchor in _BOTTOM_ANCHORS:
            out.append(SafeZoneViolation(_overlay_ref(overlay), "bottom"))
    return tuple(out)


def _find_hook_intrusions(
    composition: Composition, hook_window: tuple[float, float]
) -> tuple[HookWindowIntrusion, ...]:
    lo, hi = hook_window
    out: list[HookWindowIntrusion] = []
    for overlay in _additive(composition):
        if overlay.start < hi and overlay.end > lo:  # overlaps the reserved window
            out.append(HookWindowIntrusion(_overlay_ref(overlay), overlay.start, overlay.end))
    return tuple(out)
