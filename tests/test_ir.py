"""Neutral IR contract: JSON round-trip fidelity (it becomes Remotion `--props`) and validation."""

import json

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from videogen.kernel.ir import (
    IR,
    AudioLayer,
    Easing,
    Keyframe,
    Layer,
    MediaLayer,
    TextLayer,
    TextRun,
    TextStyle,
    Transform,
    Value,
    constant,
)

_layer_adapter: TypeAdapter[Layer] = TypeAdapter(Layer)


def assert_json_roundtrip(instance: BaseModel) -> None:
    cls = type(instance)
    restored = cls.model_validate_json(instance.model_dump_json(by_alias=True))
    assert restored == instance


def make_ir() -> IR:
    """Representative IR: all three layer kinds, a keyframed track with >1 easing, a transform."""
    return IR(
        width=1080,
        height=1920,
        fps=30,
        duration=10.0,
        layers=[
            MediaLayer(
                start=0.0,
                end=10.0,
                z=0,
                src="/renders/host.mp4",
                in_point=0.0,
                transform=Transform(
                    scale=Value(
                        keyframes=[
                            Keyframe(t=0.0, value=1.0, easing=Easing.linear),
                            Keyframe(t=3.0, value=1.2, easing=Easing.ease_in_out),
                        ]
                    )
                ),
            ),
            TextLayer(
                start=1.0,
                end=2.0,
                z=100,
                runs=[TextRun(text="WORLD", emphasis=True)],
                style="word-bold",
                props=TextStyle(font_size=76, font_weight=800, color="#FFFFFF"),
            ),
            AudioLayer(start=0.0, end=10.0, z=0, src="/renders/host.mp4"),
        ],
    )


def test_ir_roundtrips() -> None:
    assert_json_roundtrip(make_ir())


def test_ir_serializes_to_json_props() -> None:
    # The backend seam consumes a plain JSON object (passed as --props).
    payload = json.loads(make_ir().model_dump_json(by_alias=True))
    assert payload["fps"] == 30
    assert {layer["kind"] for layer in payload["layers"]} == {"media", "text", "audio"}


def test_default_opacity_is_constant_one() -> None:
    layer = AudioLayer(start=0.0, end=1.0, src="a.mp3")
    assert layer.opacity == constant(1.0)


def test_media_in_point_serializes_under_glossary_key() -> None:
    layer = MediaLayer(start=0.0, end=1.0, src="a.mp4", in_point=2.5)
    assert layer.model_dump(by_alias=True)["in"] == 2.5


# --- validation ---


def test_unknown_layer_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        _layer_adapter.validate_python({"kind": "shape", "start": 0.0, "end": 1.0})


def test_empty_keyframes_rejected() -> None:
    with pytest.raises(ValidationError):
        Value.model_validate({"keyframes": []})


def test_unknown_easing_rejected() -> None:
    with pytest.raises(ValidationError):
        Keyframe.model_validate({"t": 0.0, "value": 1.0, "easing": "bounce"})


def test_negative_keyframe_time_rejected() -> None:
    with pytest.raises(ValidationError):
        Keyframe.model_validate({"t": -1.0, "value": 1.0})


def test_text_layer_requires_runs() -> None:
    with pytest.raises(ValidationError):
        TextLayer.model_validate({"start": 0.0, "end": 1.0, "runs": [], "style": "pill"})


def test_zero_canvas_rejected() -> None:
    with pytest.raises(ValidationError):
        IR.model_validate({"width": 0, "height": 1920, "fps": 30, "duration": 10.0})
