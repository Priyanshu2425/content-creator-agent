"""Pacing reconciler (restructure/05): pure analysis over the composition + a gap-fill pass.

The Director reconciles pacing behaviorally (ADR 0008): this module detects static gaps, competing
additive-overlay collisions, safe-zone encroachment, and hook-window intrusions over the document,
and fills static gaps with content-free zoom punch-ins. All pure/deterministic — no LLM, no render.
"""

from __future__ import annotations

from videogen.agent.pacing import PacingBudget, analyze_pacing, fill_static_gaps
from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Anchor,
    Asset,
    AssetType,
    InsertOverlay,
    LayoutName,
    RegionName,
)

DURATION = 20.0


def _builder() -> Builder:
    return Builder.new(
        voiceover="host",
        duration=DURATION,
        assets={
            "host": Asset(type=AssetType.video, src="host.mp4"),
            "broll": Asset(type=AssetType.image, src="broll.png"),
        },
    )


def test_a_long_static_stretch_is_reported_as_a_gap() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")  # one scene, no other changes
    report = analyze_pacing(b.composition, duration=DURATION, budget=PacingBudget(max_static_gap=4.0))

    assert report.gaps  # 20s with a single change at 0 -> a long static stretch
    assert max(g.length for g in report.gaps) > 4.0


def test_no_gap_when_changes_are_within_the_budget() -> None:
    b = _builder()
    for i in range(10):  # a scene every 2s
        b.add_scene(LayoutName.full, float(i * 2), float(i * 2 + 2), id=f"s{i}")
    report = analyze_pacing(b.composition, duration=DURATION, budget=PacingBudget(max_static_gap=4.0))
    assert report.gaps == ()


def test_two_overlapping_inserts_are_a_competing_collision() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    b.add_overlay(InsertOverlay(start=5.0, end=9.0, asset="broll", anchor=Anchor.center))
    b.add_overlay(InsertOverlay(start=7.0, end=11.0, asset="broll", anchor=Anchor.center))
    report = analyze_pacing(b.composition, duration=DURATION)

    assert len(report.collisions) == 1
    c = report.collisions[0]
    assert c.start == 7.0 and c.end == 9.0  # the overlap window


def test_non_overlapping_inserts_do_not_collide() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    b.add_overlay(InsertOverlay(start=2.0, end=4.0, asset="broll", anchor=Anchor.center))
    b.add_overlay(InsertOverlay(start=6.0, end=8.0, asset="broll", anchor=Anchor.center))
    assert analyze_pacing(b.composition, duration=DURATION).collisions == ()


def test_bottom_anchored_insert_violates_the_safe_zone() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    b.add_overlay(InsertOverlay(start=5.0, end=8.0, asset="broll", anchor=Anchor.bottom_right))
    report = analyze_pacing(b.composition, duration=DURATION)

    assert any(v.edge == "bottom" for v in report.safe_zone_violations)


def test_centered_insert_does_not_violate_the_safe_zone() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    b.add_overlay(InsertOverlay(start=5.0, end=8.0, asset="broll", anchor=Anchor.center))
    assert analyze_pacing(b.composition, duration=DURATION).safe_zone_violations == ()


def test_insert_in_the_hook_window_is_an_intrusion() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    b.add_overlay(InsertOverlay(start=1.0, end=2.5, asset="broll", anchor=Anchor.center))
    report = analyze_pacing(
        b.composition, duration=DURATION, budget=PacingBudget(hook_window=(0.0, 3.0))
    )
    assert report.hook_window_intrusions


def test_clean_report_when_well_paced() -> None:
    b = _builder()
    for i in range(10):
        b.add_scene(LayoutName.full, float(i * 2), float(i * 2 + 2), id=f"s{i}")
    report = analyze_pacing(b.composition, duration=DURATION)
    assert report.is_clean


def test_fill_static_gaps_adds_a_zoom_punch_in_over_the_gap() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 20.0, id="s0")
    before = len(b.composition.overlays)

    added = fill_static_gaps(b, duration=DURATION, budget=PacingBudget(max_static_gap=4.0))

    assert added >= 1
    assert len(b.composition.overlays) == before + added
    # the new change breaks the static stretch -> re-analysis finds no gap
    assert analyze_pacing(b.composition, duration=DURATION, budget=PacingBudget(max_static_gap=4.0)).gaps == ()


def test_fill_static_gaps_is_a_noop_when_already_paced() -> None:
    b = _builder()
    for i in range(10):
        b.add_scene(LayoutName.full, float(i * 2), float(i * 2 + 2), id=f"s{i}")
    assert fill_static_gaps(b, duration=DURATION) == 0
