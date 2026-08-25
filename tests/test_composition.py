"""Composition contract: JSON round-trip fidelity and per-model field validation.

Cross-cutting semantic checks (scene overlap, gaps, region validity, caption alignment) are
the Phase 4 validator's job and are deliberately not tested here.
"""

import pytest
from pydantic import BaseModel, ValidationError

from videogen.kernel.composition import (
    Anchor,
    Asset,
    AssetType,
    Audio,
    Caption,
    Composition,
    InsertOverlay,
    LayoutName,
    Overlay,
    PanOverlay,
    Ref,
    RegionName,
    Scene,
    Transition,
    TransitionKind,
    ZoomOverlay,
)


def assert_json_roundtrip(instance: BaseModel) -> None:
    """Serialize with glossary aliases, parse back, and assert equality (the contract)."""
    cls = type(instance)
    restored = cls.model_validate_json(instance.model_dump_json(by_alias=True))
    assert restored == instance


def make_composition() -> Composition:
    """A representative document exercising the decision-bearing shapes."""
    overlays: list[Overlay] = [
        ZoomOverlay(start=3.0, end=6.0, target=RegionName.full, z=0),  # transform
        InsertOverlay(start=4.0, end=5.0, target=RegionName.full, z=10, asset="tweet"),  # additive
    ]
    return Composition(
        version=1,
        strict=True,
        assets={
            "host_cam": Asset(type=AssetType.video, src="host.mp4"),
            "tweet": Asset(type=AssetType.image, src="tweet.png"),
            "vo": Asset(type=AssetType.audio, src="host.mp4"),
        },
        voiceover=Audio(asset="vo"),
        scenes=[
            Scene(
                id="hook",
                start=0.0,
                end=3.0,
                layout=LayoutName.split_h,
                regions={
                    RegionName.top: Ref(asset="host_cam"),  # no in-point
                    RegionName.bottom: Ref(asset="tweet", in_point=2.0),  # with in-point
                },
            ),
            Scene(
                id="body",
                start=3.0,
                end=10.0,
                layout=LayoutName.full,
                regions={RegionName.full: Ref(asset="host_cam", in_point=3.0)},
            ),
        ],
        transitions=[  # sparse: only the one non-cut boundary, keyed by afterScene
            Transition(after_scene="hook", kind=TransitionKind.crossfade, duration=0.4),
        ],
        overlays=overlays,
        captions=[
            Caption(text="hello", start=0.0, end=1.0, style="pill"),
            Caption(text="WORLD", start=1.0, end=2.0, style="word-bold"),
            Caption(text="pop", start=2.0, end=3.0, style="kinetic"),
        ],
    )


def test_composition_roundtrips() -> None:
    assert_json_roundtrip(make_composition())


def test_in_point_serializes_under_glossary_key() -> None:
    # The wire form must carry `in` (glossary), not the Python field name `in_point`.
    ref = Ref(asset="tweet", in_point=2.0)
    dumped = ref.model_dump(by_alias=True)
    assert dumped == {"asset": "tweet", "in": 2.0, "crop": None}  # crop defaults None


def test_transition_keyed_by_after_scene() -> None:
    t = Transition(after_scene="hook", kind=TransitionKind.crossfade)
    assert t.model_dump(by_alias=True)["afterScene"] == "hook"


def test_strict_flag_defaults_on() -> None:
    comp = Composition(voiceover=Audio(asset="vo"))
    assert comp.strict is True
    assert comp.version == 1


# --- validation: malformed documents are rejected ---


def test_unknown_asset_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset.model_validate({"type": "gif", "src": "x.gif"})


def test_unknown_overlay_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Composition.model_validate(
            {
                "voiceover": {"asset": "vo"},
                "overlays": [{"type": "spin", "start": 0.0, "end": 1.0}],
            }
        )


def test_unknown_caption_style_rejected() -> None:
    with pytest.raises(ValidationError):
        Caption.model_validate({"text": "x", "start": 0.0, "end": 1.0, "style": "bold"})


def test_missing_envelope_field_rejected() -> None:
    # `start` is a required Envelope field.
    with pytest.raises(ValidationError):
        ZoomOverlay.model_validate({"type": "zoom", "end": 1.0})


def test_negative_time_rejected() -> None:
    with pytest.raises(ValidationError):
        Caption.model_validate({"text": "x", "start": -1.0, "end": 1.0, "style": "pill"})


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset.model_validate({"type": "video", "src": "x.mp4", "fps": 30})


def test_ref_requires_asset() -> None:
    with pytest.raises(ValidationError):
        Ref.model_validate({"in": 1.0})


# --- overlay type-specific params (Phase 6): the registry-driven half of the two-phase split ---


def test_zoom_carries_scale_params_with_defaults() -> None:
    # The envelope is fixed; the type-specific params live on the typed overlay member.
    z = ZoomOverlay(start=0.0, end=2.0)
    assert (z.from_scale, z.to_scale) == (1.0, 1.2)


def test_pan_carries_offset_params_with_defaults() -> None:
    p = PanOverlay(start=0.0, end=2.0)
    assert (p.dx, p.dy) == (0.1, 0.0)


def test_insert_requires_an_asset() -> None:
    # A floating insert without media is meaningless: the envelope alone is not a valid insert.
    with pytest.raises(ValidationError):
        InsertOverlay.model_validate({"type": "insert", "start": 0.0, "end": 1.0})


def test_insert_carries_anchor_scale_and_in_point_under_glossary_keys() -> None:
    ins = InsertOverlay(
        start=0.0, end=1.0, asset="tweet", anchor=Anchor.top_right, scale=0.3, in_point=2.0
    )
    dumped = ins.model_dump(by_alias=True)
    assert dumped["asset"] == "tweet"
    assert dumped["anchor"] == "top-right"
    assert dumped["scale"] == 0.3
    assert dumped["in"] == 2.0  # the Reference in-point alias, reused for an insert's source slice


def test_insert_anchor_defaults_to_top_right() -> None:
    assert InsertOverlay(start=0.0, end=1.0, asset="tweet").anchor is Anchor.top_right


def test_unknown_layout_rejected() -> None:
    with pytest.raises(ValidationError):
        Scene.model_validate({"id": "s", "start": 0.0, "end": 1.0, "layout": "pip", "regions": {}})


def test_unknown_region_slot_rejected() -> None:
    with pytest.raises(ValidationError):
        Scene.model_validate(
            {
                "id": "s",
                "start": 0.0,
                "end": 1.0,
                "layout": "full",
                "regions": {"middle": {"asset": "host_cam"}},
            }
        )
