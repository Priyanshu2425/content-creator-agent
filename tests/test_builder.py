"""Builder: imperative CRUD over a declarative Composition, validated per operation (ADR 0004).

Tests assert external behavior -- the resulting document (round-tripped through the Phase 1 types),
the operation's validation outcome, and the transactional guarantee that a rejected op leaves the
Composition untouched -- never the Builder's internals.
"""

from __future__ import annotations

from collections.abc import Iterable

from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Asset,
    AssetType,
    CaptionStyle,
    LayoutName,
    RegionName,
)
from videogen.kernel.validator import ErrorCode, GlobalWarning, LocalError, WarningCode
from videogen.services.media import Transcript, Word

DURATION = 10.0

_ASSETS = {
    "vo": Asset(type=AssetType.audio, src="vo.m4a"),
    "host": Asset(type=AssetType.video, src="host.mp4"),
    "broll": Asset(type=AssetType.image, src="tweet.png"),
}


def _builder() -> Builder:
    return Builder.new(voiceover="vo", duration=DURATION, assets=_ASSETS)


def _codes(items: Iterable[LocalError | GlobalWarning]) -> set[ErrorCode | WarningCode]:
    return {item.code for item in items}


# --- construction ---


def test_new_builds_a_minimal_composition() -> None:
    b = _builder()
    comp = b.composition
    assert comp.voiceover.asset == "vo"
    assert comp.scenes == []
    assert comp.captions == []


# --- the simplest authoring path: one full-frame host scene (user story 11) ---


def test_simplest_talking_head_is_gate_clean() -> None:
    b = _builder()
    sid = b.add_scene(LayoutName.full, 0.0, DURATION, id="s0").entity_ref
    result = b.fill_region("s0", RegionName.full, "host")
    assert sid == "s0"
    assert result.ok
    assert b.can_submit_render()
    scene = b.get_scene("s0")
    assert scene is not None
    assert scene.regions[RegionName.full].asset == "host"


def test_add_scene_assigns_a_stable_id_when_omitted() -> None:
    b = _builder()
    first = b.add_scene(LayoutName.full, 0.0, 4.0)
    second = b.add_scene(LayoutName.full, 4.0, 8.0)
    assert first.ok and second.ok
    ids = [s.id for s in b.composition.scenes]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert all(ids)  # non-empty


def test_op_result_round_trips_through_the_contract_types() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host", in_point=1.5)
    comp = b.composition
    restored = type(comp).model_validate_json(comp.model_dump_json(by_alias=True))
    assert restored == comp
    assert restored.scenes[0].regions[RegionName.full].in_point == 1.5


# --- captions ---


def test_add_caption_appends_to_the_captions_track() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    result = b.add_caption("hello", 0.2, 0.8, CaptionStyle.pill)
    assert result.ok
    assert [c.text for c in b.composition.captions] == ["hello"]


def test_add_captions_from_transcript_maps_words_to_absolute_seconds() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    transcript = Transcript(
        words=[
            Word(text="hello", start=0.2, end=0.5),
            Word(text="world", start=0.5, end=0.9),
            Word(text="now", start=1.0, end=1.4),
        ]
    )
    result = b.add_captions_from_transcript(transcript, style=CaptionStyle.word_bold)
    assert result.ok
    caps = b.composition.captions
    assert [(c.text, c.start, c.end) for c in caps] == [
        ("hello", 0.2, 0.5),
        ("world", 0.5, 0.9),
        ("now", 1.0, 1.4),
    ]
    assert all(c.style == CaptionStyle.word_bold for c in caps)


# --- per-op validation + transactional rollback (user stories 6, 31) ---


def test_fill_region_outside_layout_is_rejected_and_leaves_doc_unchanged() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    result = b.fill_region("s0", RegionName.top, "host")  # `full` layout has no `top`
    assert not result.ok
    assert ErrorCode.REGION_NOT_IN_LAYOUT in _codes(result.errors)
    assert RegionName.top not in b.get_scene("s0").regions  # type: ignore[union-attr]


def test_caption_out_of_bounds_is_rejected_and_leaves_doc_unchanged() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    result = b.add_caption("late", 9.0, 12.0, CaptionStyle.pill)
    assert not result.ok
    assert ErrorCode.CAPTION_OUT_OF_BOUNDS in _codes(result.errors)
    assert b.composition.captions == []


def test_fill_region_dangling_asset_is_rejected() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    result = b.fill_region("s0", RegionName.full, "ghost")
    assert not result.ok
    assert ErrorCode.DANGLING_ASSET in _codes(result.errors)


def test_overlapping_scene_op_is_rejected_and_first_scene_survives() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 6.0, id="a")
    b.fill_region("a", RegionName.full, "host")
    result = b.add_scene(LayoutName.full, 5.0, 10.0, id="b")  # overlaps `a`
    assert not result.ok
    assert ErrorCode.SCENE_OVERLAP in _codes(result.errors)
    assert [s.id for s in b.composition.scenes] == ["a"]  # `b` not committed


# --- gap warnings commit (warnings never roll back; user story 18) ---


def test_gap_warning_commits_the_operation() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="a")
    b.fill_region("a", RegionName.full, "host")
    result = b.add_scene(LayoutName.full, 6.0, 10.0, id="b")  # leaves a gap [4, 6]
    assert result.ok  # a warning is not an error
    assert WarningCode.SCENE_GAP in _codes(result.warnings)
    assert [s.id for s in b.composition.scenes] == ["a", "b"]  # both committed


# --- op-precondition errors (unknown / duplicate entities) ---


def test_fill_region_unknown_scene_is_an_error() -> None:
    b = _builder()
    result = b.fill_region("ghost", RegionName.full, "host")
    assert not result.ok
    assert ErrorCode.UNKNOWN_SCENE in _codes(result.errors)


def test_duplicate_scene_id_is_rejected() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="dup")
    result = b.add_scene(LayoutName.full, 4.0, 8.0, id="dup")
    assert not result.ok
    assert ErrorCode.DUPLICATE_SCENE_ID in _codes(result.errors)
    assert len(b.composition.scenes) == 1


# --- update ---


def test_retime_scene_updates_in_place() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    result = b.retime_scene("s0", start=0.0, end=8.0)
    assert result.ok
    assert b.get_scene("s0").end == 8.0  # type: ignore[union-attr]


def test_retime_into_overlap_is_rejected_and_preserves_timing() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 4.0, id="a")
    b.fill_region("a", RegionName.full, "host")
    b.add_scene(LayoutName.full, 4.0, 8.0, id="b")
    b.fill_region("b", RegionName.full, "host")
    result = b.retime_scene("a", start=0.0, end=6.0)  # would overlap `b`
    assert not result.ok
    assert b.get_scene("a").end == 4.0  # type: ignore[union-attr]


def test_update_caption_restyles() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    b.add_caption("hi", 0.0, 1.0, CaptionStyle.pill)
    result = b.update_caption(0, style=CaptionStyle.kinetic)
    assert result.ok
    assert b.composition.captions[0].style == CaptionStyle.kinetic


# --- delete ---


def test_delete_scene_removes_it() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    result = b.delete_scene("s0")
    assert result.ok
    assert b.composition.scenes == []


def test_delete_caption_removes_it() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    b.add_caption("a", 0.0, 1.0, CaptionStyle.pill)
    b.add_caption("b", 1.0, 2.0, CaptionStyle.pill)
    result = b.delete_caption(0)
    assert result.ok
    assert [c.text for c in b.composition.captions] == ["b"]


def test_delete_unknown_scene_is_an_error() -> None:
    b = _builder()
    result = b.delete_scene("ghost")
    assert not result.ok
    assert ErrorCode.UNKNOWN_SCENE in _codes(result.errors)


# --- read + on-demand validation (user story 33) ---


def test_get_scene_returns_none_for_unknown_id() -> None:
    assert _builder().get_scene("nope") is None


def test_validate_runs_over_the_whole_document_on_demand() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    assert b.validate().ok
    assert b.can_submit_render()
