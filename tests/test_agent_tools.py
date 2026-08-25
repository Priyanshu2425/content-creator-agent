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
)
from videogen.kernel.builder import Builder
from videogen.kernel.composition import (
    Asset,
    AssetType,
    LayoutName,
    RegionName,
    TransitionKind,
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
    direct = fresh_builder().add_caption("hi", 0.2, 0.8, "word-bold")

    assert via_tool == direct


def test_base_captions_take_the_brand_kit_default_style_when_unspecified() -> None:
    # Base captions (auto-populated transcript track) default to the brand kit's caption style id
    # when the Director names none (ADR 0010 / caption-library issue 04).
    b = fresh_builder()
    apply_op(
        b,
        "add_captions_from_transcript",
        {},
        transcript=TRANSCRIPT,
        default_caption_style="highlight-box",
    )
    assert b.composition.captions
    assert all(c.style == "highlight-box" for c in b.composition.captions)


def test_feature_caption_style_overrides_the_brand_kit_default() -> None:
    # A deliberately chosen (feature) style wins over the brand kit default.
    b = fresh_builder()
    apply_op(
        b,
        "add_captions_from_transcript",
        {"style": "kinetic"},
        transcript=TRANSCRIPT,
        default_caption_style="pill",
    )
    assert all(c.style == "kinetic" for c in b.composition.captions)


def test_add_captions_from_transcript_tool_mirrors_the_builder_op() -> None:
    via_tool = _dispatch(fresh_builder(), "add_captions_from_transcript", {"style": "kinetic"})
    direct = fresh_builder().add_captions_from_transcript(TRANSCRIPT, style="kinetic")

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


# Overlays (zoom/pan/insert) live on the Builder but are deliberately NOT a Director tool: the model
# never calls add_overlay directly -- overlays are placed internally (e.g. by add_title) or by the
# motion-graphics worker. The Builder op itself is covered in test_builder.py / test_overlays.py.


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


def test_crop_tools_are_live_and_dispatch_to_set_crop() -> None:
    # crop_image/crop_video are activated as mutating tools (no longer DRAFT).
    assert {"crop_image", "crop_video"} <= {tool.name for tool in TOOLS}
    assert {"crop_image", "crop_video"} <= MUTATING_OPS

    builder = fresh_builder()
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    result = _dispatch(
        builder,
        "crop_video",
        {"scene_id": "s0", "region": "full", "x": 0.1, "y": 0.0, "width": 0.8, "height": 1.0},
    )

    assert result.ok  # mirrors builder.set_crop
    crop = builder.composition.scenes[0].regions[RegionName.full].crop
    assert crop is not None
    assert (crop.x, crop.y, crop.width, crop.height) == (0.1, 0.0, 0.8, 1.0)


def _enum_choices(tool_name: str, prop: str) -> list[str]:
    spec = next(tool for tool in TOOLS if tool.name == tool_name)
    props = spec.input_schema["properties"]
    return list(props[prop]["enum"])  # type: ignore[index]


@pytest.mark.parametrize(
    ("tool_name", "prop", "enum_cls"),
    [
        ("add_scene", "layout", LayoutName),
        ("fill_region", "region", RegionName),
        ("set_transition", "kind", TransitionKind),
    ],
)
def test_enum_choices_are_derived_from_the_kernel_enums(tool_name, prop, enum_cls) -> None:  # type: ignore[no-untyped-def]
    assert _enum_choices(tool_name, prop) == [member.value for member in enum_cls]


def test_caption_style_choices_are_derived_from_the_caption_registry() -> None:
    # Caption styles are an open registry (ADR 0010), not a closed enum: the tool's choices come from
    # the caption style registry, so a newly registered visual is offered without editing the tool.
    from videogen.plugins.captions.registry import caption_style_ids

    assert set(_enum_choices("add_caption", "style")) == set(caption_style_ids())
