"""GeminiDescribeAgent batches every image asset into a single structured call.

The external SDK call is faked: the test pins the part that is ours — image-only selection, a
single ``generate_content`` carrying one labelled inline part per image, and mapping the returned
array back to ``AssetDescription`` by ``asset_id``. Video/audio assets are skipped, and the model
omitting an asset simply leaves it undescribed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from videogen.agent.gemini_describe import GeminiDescribeAgent
from videogen.agent.perception import AssetFact


class _FakeGenai:
    """Records every generate_content call; replays a canned JSON array as the response text."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._rows = rows

    def _generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(self._rows))


def _png(path: Path) -> str:
    path.write_bytes(b"\x89PNG-fake")
    return str(path)


def test_describe_all_batches_images_into_one_call_and_maps_by_id(tmp_path: Path) -> None:
    assets = [
        AssetFact(id="a1", type="image", source=_png(tmp_path / "a1.png")),
        AssetFact(id="a2", type="image", source=_png(tmp_path / "a2.png")),
        AssetFact(id="v1", type="video", source=str(tmp_path / "v1.mp4")),  # skipped, never read
        AssetFact(id="au1", type="audio", source=str(tmp_path / "au1.mp3")),  # skipped
    ]
    client = _FakeGenai(
        rows=[
            {"asset_id": "a2", "description": "a chart", "usage_advice": "on 'growth'"},
            {"asset_id": "a1", "description": "a headline", "usage_advice": "on 'study'"},
        ]
    )
    agent = GeminiDescribeAgent(model="gemini-2.5-flash-lite", client=client)

    out = agent.describe_all(assets, brief="b", transcript="t")

    # exactly one model call, regardless of asset count
    assert len(client.calls) == 1
    contents = client.calls[0]["contents"]
    # one label + one inline part per image, video/audio excluded
    assert "Asset a1:" in contents and "Asset a2:" in contents
    assert "Asset v1:" not in contents
    inline_parts = [c for c in contents if isinstance(c, dict) and "inline_data" in c]
    assert len(inline_parts) == 2
    # mapped back by asset_id (order in the response is irrelevant)
    assert out["a1"].description == "a headline"
    assert out["a2"].usage_advice == "on 'growth'"
    assert set(out) == {"a1", "a2"}


def test_describe_all_returns_empty_when_no_image_assets(tmp_path: Path) -> None:
    client = _FakeGenai(rows=[])
    agent = GeminiDescribeAgent(client=client)

    out = agent.describe_all(
        [AssetFact(id="v1", type="video", source="v1.mp4")], brief="b", transcript="t"
    )

    assert out == {}
    assert client.calls == []  # no images -> no call at all


def test_describe_all_drops_assets_the_model_omits(tmp_path: Path) -> None:
    assets = [
        AssetFact(id="a1", type="image", source=_png(tmp_path / "a1.png")),
        AssetFact(id="a2", type="image", source=_png(tmp_path / "a2.png")),
    ]
    client = _FakeGenai(
        rows=[{"asset_id": "a1", "description": "only one", "usage_advice": "here"}]
    )
    agent = GeminiDescribeAgent(client=client)

    out = agent.describe_all(assets, brief="b", transcript="t")

    assert set(out) == {"a1"}  # a2 omitted by the model -> simply undescribed
