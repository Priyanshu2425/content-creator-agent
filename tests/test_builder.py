"""Builder: imperative CRUD over a declarative Composition, validated per operation (ADR 0004).

Tests assert external behavior -- the resulting document (round-tripped through the Phase 1 types),
the operation's validation outcome, and the transactional guarantee that a rejected op leaves the
Composition untouched -- never the Builder's internals.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Asset,
    AssetType,
    CropRect,
    InsertOverlay,
    LayoutName,
    RegionName,
    TransitionKind,
    ZoomOverlay,
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


def test_set_crop_narrows_an_existing_fill_and_stays_gate_clean() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    result = b.set_crop("s0", RegionName.full, CropRect(x=0.1, y=0.0, width=0.8, height=1.0))
    assert result.ok and b.can_submit_render()
    crop = b.get_scene("s0").regions[RegionName.full].crop  # type: ignore[union-attr]
    assert crop == CropRect(x=0.1, y=0.0, width=0.8, height=1.0)


def test_set_crop_on_an_unfilled_region_is_rejected_and_leaves_doc_unchanged() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    result = b.set_crop("s0", RegionName.full, CropRect(x=0.0, y=0.0, width=1.0, height=1.0))
    assert not result.ok
    assert ErrorCode.REGION_NOT_FILLED in _codes(result.errors)
    assert b.get_scene("s0").regions == {}  # type: ignore[union-attr]


def test_crop_rect_rejects_a_window_outside_the_source() -> None:
    with pytest.raises(ValueError):  # x + width > 1 is not a valid source sub-rect
        CropRect(x=0.5, y=0.0, width=0.8, height=1.0)


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
    result = b.add_caption("hello", 0.2, 0.8, "pill")
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
    result = b.add_captions_from_transcript(transcript, style="word-bold")
    assert result.ok
    caps = b.composition.captions
    # the three words (no pause over the line-break gap, under the word cap) form one karaoke line
    assert len(caps) == 1
    assert caps[0].text == "hello world now"
    assert caps[0].start == 0.2 and caps[0].end == 1.4
    assert [(w.text, w.start, w.end) for w in caps[0].words] == [
        ("hello", 0.2, 0.5),
        ("world", 0.5, 0.9),
        ("now", 1.0, 1.4),
    ]
    assert caps[0].style == "word-bold"


def test_add_captions_breaks_lines_on_a_natural_pause() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    transcript = Transcript(
        words=[
            Word(text="hello", start=0.2, end=0.5),
            Word(text="world", start=0.5, end=0.9),
            Word(text="again", start=2.0, end=2.4),  # 1.1s pause -> new line
        ]
    )
    result = b.add_captions_from_transcript(transcript)
    assert result.ok
    caps = b.composition.captions
    assert [c.text for c in caps] == ["hello world", "again"]


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
    result = b.add_caption("late", 9.0, 12.0, "pill")
    assert not result.ok
    assert ErrorCode.CAPTION_OUT_OF_BOUNDS in _codes(result.errors)
    assert b.composition.captions == []


def test_fill_region_dangling_asset_is_rejected() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    result = b.fill_region("s0", RegionName.full, "ghost")
    assert not result.ok
    assert ErrorCode.DANGLING_ASSET in _codes(result.errors)


# --- layouts: split-h with a ratio param (Phase 5) ---


def test_add_scene_stores_layout_params() -> None:
    b = _builder()
    result = b.add_scene(LayoutName.split_h, 0.0, DURATION, id="s0", layout_params={"ratio": 0.7})
    assert result.ok
    scene = b.get_scene("s0")
    assert scene is not None
    assert scene.layout_params == {"ratio": 0.7}


def test_add_scene_with_out_of_range_ratio_is_rejected() -> None:
    # The split-h contract's ratio validity is enforced through the Builder's per-op validation.
    b = _builder()
    result = b.add_scene(LayoutName.split_h, 0.0, DURATION, id="s0", layout_params={"ratio": 1.5})
    assert not result.ok
    assert ErrorCode.LAYOUT_PARAM_INVALID in _codes(result.errors)
    assert b.composition.scenes == []  # transactional: nothing committed


def test_author_a_split_h_hook_filling_top_and_bottom() -> None:
    b = _builder()
    b.add_scene(LayoutName.split_h, 0.0, DURATION, id="hook", layout_params={"ratio": 0.6})
    assert b.fill_region("hook", RegionName.top, "host").ok
    assert b.fill_region("hook", RegionName.bottom, "broll").ok
    assert b.can_submit_render()


# --- transitions: sparse, keyed by afterScene (Phase 5) ---


def test_add_transition_after_a_known_scene_commits() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, 5.0, id="a")
    b.fill_region("a", RegionName.full, "host")
    b.add_scene(LayoutName.full, 5.0, DURATION, id="b")
    b.fill_region("b", RegionName.full, "broll")
    result = b.add_transition("a", TransitionKind.crossfade, duration=0.5)
    assert result.ok
    assert result.entity_ref == "a"
    transitions = b.composition.transitions
    assert len(transitions) == 1
    assert transitions[0].after_scene == "a"
    assert transitions[0].kind is TransitionKind.crossfade


def test_add_transition_naming_an_unknown_scene_is_rejected() -> None:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="a")
    b.fill_region("a", RegionName.full, "host")
    result = b.add_transition("ghost", TransitionKind.crossfade)
    assert not result.ok
    assert ErrorCode.DANGLING_TRANSITION in _codes(result.errors)
    assert b.composition.transitions == []  # transactional: nothing committed


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
    b.add_caption("hi", 0.0, 1.0, "pill")
    result = b.update_caption(0, style="kinetic")
    assert result.ok
    assert b.composition.captions[0].style == "kinetic"


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
    b.add_caption("a", 0.0, 1.0, "pill")
    b.add_caption("b", 1.0, 2.0, "pill")
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


# --- effect overlays through the shared addOverlay envelope (Phase 6, stories 8, 9) ---


def _host_builder() -> Builder:
    b = _builder()
    b.add_scene(LayoutName.full, 0.0, DURATION, id="s0")
    b.fill_region("s0", RegionName.full, "host")
    return b


def test_add_overlay_commits_a_valid_effect() -> None:
    b = _host_builder()
    result = b.add_overlay(ZoomOverlay(start=1.0, end=3.0, target=RegionName.full))
    assert result.ok
    assert len(b.composition.overlays) == 1
    assert b.composition.overlays[0].type == "zoom"


def test_add_overlay_validates_params_and_rolls_back_a_bad_value() -> None:
    b = _host_builder()
    result = b.add_overlay(ZoomOverlay(start=1.0, end=3.0, target=RegionName.full, from_scale=-1.0))
    assert not result.ok
    assert ErrorCode.OVERLAY_PARAM_INVALID in _codes(result.errors)
    assert b.composition.overlays == []  # transactional: a rejected op commits nothing


def test_add_overlay_rejects_a_target_region_not_exposed() -> None:
    b = _host_builder()  # a `full` layout never exposes `top`
    result = b.add_overlay(InsertOverlay(start=1.0, end=2.0, target=RegionName.top, asset="broll"))
    assert not result.ok
    assert ErrorCode.TARGET_REGION_INVALID in _codes(result.errors)
    assert b.composition.overlays == []


def test_add_overlay_rejects_a_dangling_insert_asset() -> None:
    b = _host_builder()
    result = b.add_overlay(InsertOverlay(start=1.0, end=2.0, target=RegionName.full, asset="ghost"))
    assert not result.ok
    assert ErrorCode.DANGLING_ASSET in _codes(result.errors)


# --- add_asset: registering worker-generated assets mid-run (restructure/03, ADR 0008) --------


def test_add_asset_registers_a_new_asset_into_the_library() -> None:
    builder = Builder.new(voiceover="host", duration=DURATION, assets={
        "host": Asset(type=AssetType.video, src="host.mp4"),
    })
    result = builder.add_asset("broll_1", Asset(type=AssetType.image, src="broll_1.png"))

    assert result.ok
    assert builder.composition.assets["broll_1"].src == "broll_1.png"


def test_add_asset_rejects_a_duplicate_id_and_leaves_the_library_untouched() -> None:
    builder = Builder.new(voiceover="host", duration=DURATION, assets={
        "host": Asset(type=AssetType.video, src="host.mp4"),
    })
    result = builder.add_asset("host", Asset(type=AssetType.image, src="other.png"))

    assert not result.ok
    assert any(e.code is ErrorCode.DUPLICATE_ASSET_ID for e in result.errors)
    assert builder.composition.assets["host"].src == "host.mp4"  # unchanged


# --- set_scene_audio: cut-bound SFX placement (sfx/02, ADR 0009) -------------------------------


def test_set_scene_audio_attaches_a_sound_to_a_cut() -> None:
    builder = Builder.new(voiceover="host", duration=DURATION, assets={
        "host": Asset(type=AssetType.video, src="host.mp4"),
    })
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    result = builder.set_scene_audio("s0", "whoosh", reason="b-roll entry")

    assert result.ok
    scene = builder.get_scene("s0")
    assert scene is not None and scene.audio is not None
    assert scene.audio.sound.value == "whoosh"


def test_set_scene_audio_rejects_an_unknown_scene() -> None:
    builder = Builder.new(voiceover="host", duration=DURATION, assets={
        "host": Asset(type=AssetType.video, src="host.mp4"),
    })
    result = builder.set_scene_audio("nope", "click")
    assert not result.ok
    assert any(e.code is ErrorCode.UNKNOWN_SCENE for e in result.errors)
