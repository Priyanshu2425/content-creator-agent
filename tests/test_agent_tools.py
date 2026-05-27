"""Tool surface: Builder ops as tools, dispatched with fidelity to the kernel (Phase 8, ADR 0004).

The tools must not drift from the operations they wrap (maintainer story 29): every exposed mutating
tool maps to a real Builder op, and a tool call with given arguments produces *exactly* the same
Composition mutation and OpResult as calling that Builder op directly. These tests lean on Phase 4's
known-good kernel as the oracle -- they never assert tool internals, only that tool == Builder.
No model and no backend are needed; this is the deterministic, kernel-adjacent layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from videogen.agent.tools import (
    FINISH_OP,
    MUTATING_OPS,
    TOOLS,
    VISION_OPS,
    apply_op,
    build_overlay,
)
from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Anchor,
    Asset,
    AssetType,
    CaptionStyle,
    InsertOverlay,
    LayoutName,
    PanOverlay,
    RegionName,
    TransitionKind,
    ZoomOverlay,
)


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


TRANSCRIPT = _Transcript([_Word("hello", 0.0, 0.5), _Word("world", 0.5, 1.0)])


def fresh_builder() -> Builder:
    """A Builder seeded with the media facts: a host video asset and the voiceover master clock."""
    return Builder.new(
        voiceover="host",
        duration=2.0,
        assets={
            "host": Asset(type=AssetType.video, src="host.mp4"),
            "broll": Asset(type=AssetType.image, src="broll.png"),
        },
    )


def _dispatch(builder: Builder, name: str, args: dict[str, object]):  # type: ignore[no-untyped-def]
    return apply_op(builder, name, args, transcript=TRANSCRIPT)


# --- one test per op: the tool call mirrors the direct Builder call exactly ---


def test_add_scene_tool_mirrors_the_builder_op() -> None:
    scene_args = {"layout": "full", "start": 0.0, "end": 2.0, "id": "s0"}
    via_tool = _dispatch(fresh_builder(), "add_scene", dict(scene_args))
    direct_b = fresh_builder()
    direct = direct_b.add_scene(LayoutName.full, 0.0, 2.0, id="s0")

    assert via_tool == direct


def test_fill_region_tool_mirrors_the_builder_op() -> None:
    b_tool = fresh_builder()
    b_tool.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    via_tool = _dispatch(
        b_tool, "fill_region", {"scene_id": "s0", "region": "full", "asset_id": "host"}
    )

    b_direct = fresh_builder()
    b_direct.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    direct = b_direct.fill_region("s0", RegionName.full, "host")

    assert via_tool == direct
    assert b_tool.composition == b_direct.composition


def test_add_caption_tool_mirrors_the_builder_op() -> None:
    via_tool = _dispatch(
        fresh_builder(),
        "add_caption",
        {"text": "hi", "start": 0.2, "end": 0.8, "style": "word-bold"},
    )
    direct = fresh_builder().add_caption("hi", 0.2, 0.8, CaptionStyle.word_bold)

    assert via_tool == direct


def test_add_captions_from_transcript_tool_mirrors_the_builder_op() -> None:
    via_tool = _dispatch(fresh_builder(), "add_captions_from_transcript", {"style": "kinetic"})
    direct = fresh_builder().add_captions_from_transcript(TRANSCRIPT, style=CaptionStyle.kinetic)

    assert via_tool == direct


def test_set_transition_tool_mirrors_the_builder_add_transition_op() -> None:
    b_tool = fresh_builder()
    b_tool.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    via_tool = _dispatch(b_tool, "set_transition", {"after_scene": "s0", "kind": "crossfade"})

    b_direct = fresh_builder()
    b_direct.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    direct = b_direct.add_transition("s0", TransitionKind.crossfade)

    assert via_tool == direct
    assert b_tool.composition == b_direct.composition


# --- add_overlay: flat tool args build the right Overlay subclass via the kernel union ---


def test_build_overlay_constructs_each_subclass_from_flat_args() -> None:
    zoom = build_overlay(
        {"type": "zoom", "start": 0.0, "end": 2.0, "params": {"from_scale": 1.0, "to_scale": 1.3}}
    )
    pan = build_overlay(
        {"type": "pan", "start": 0.0, "end": 2.0, "params": {"dx": 0.1, "dy": 0.0}}
    )
    insert = build_overlay(
        {
            "type": "insert",
            "start": 0.0,
            "end": 1.0,
            "params": {"asset": "broll", "anchor": "top-right", "scale": 0.3},
        }
    )

    assert isinstance(zoom, ZoomOverlay) and zoom.to_scale == 1.3
    assert isinstance(pan, PanOverlay) and pan.dx == 0.1
    assert isinstance(insert, InsertOverlay)
    assert insert.asset == "broll" and insert.anchor is Anchor.top_right


def test_add_overlay_tool_mirrors_the_builder_op() -> None:
    b_tool = fresh_builder()
    b_tool.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    via_tool = _dispatch(
        b_tool,
        "add_overlay",
        {"type": "zoom", "start": 0.0, "end": 2.0, "params": {"from_scale": 1.0, "to_scale": 1.2}},
    )

    b_direct = fresh_builder()
    b_direct.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    direct = b_direct.add_overlay(ZoomOverlay(start=0.0, end=2.0, from_scale=1.0, to_scale=1.2))

    assert via_tool == direct
    assert b_tool.composition == b_direct.composition


# --- self-correction: an invalid op is rejected and leaves the document untouched ---


def test_invalid_op_is_rejected_and_leaves_the_composition_unchanged() -> None:
    builder = fresh_builder()
    before = builder.composition

    result = _dispatch(builder, "add_scene", {"layout": "full", "start": 0.0, "end": 5.0})

    assert not result.ok  # scene end 5.0 exceeds the 2.0 voiceover -> hard error fed back
    assert builder.composition == before  # transactional: the rejected op did not mutate


# --- anti-drift: the tool table matches the kernel surface (story 29) ---


def test_tool_table_covers_the_expected_surface_and_classifies_each_tool() -> None:
    names = {tool.name for tool in TOOLS}
    assert names == MUTATING_OPS | VISION_OPS | {FINISH_OP}
    assert {"render_still", "scene_preview"} == VISION_OPS
    assert FINISH_OP == "finish"


def _enum_choices(tool_name: str, prop: str) -> list[str]:
    spec = next(tool for tool in TOOLS if tool.name == tool_name)
    props = spec.input_schema["properties"]
    return list(props[prop]["enum"])  # type: ignore[index]


@pytest.mark.parametrize(
    ("tool_name", "prop", "enum_cls"),
    [
        ("add_scene", "layout", LayoutName),
        ("fill_region", "region", RegionName),
        ("add_caption", "style", CaptionStyle),
        ("set_transition", "kind", TransitionKind),
    ],
)
def test_enum_choices_are_derived_from_the_kernel_enums(tool_name, prop, enum_cls) -> None:  # type: ignore[no-untyped-def]
    assert _enum_choices(tool_name, prop) == [member.value for member in enum_cls]


def test_add_overlay_type_choices_match_the_overlay_union() -> None:
    assert set(_enum_choices("add_overlay", "type")) == {"zoom", "pan", "insert"}
