"""GeminiReviewAgent: the real video-capable ReviewAgent over google-genai (Phase 9, Phase 8b seam).

The video upload + generate call is gated behind an API key and the SDK, so these tests cover the
deterministic part: parsing the model's structured JSON into the neutral ``ReviewFeedback`` the
finalization gate consumes, and the upload -> generate -> parse orchestration against a fake client
(no key, no network). The full-motion judgement itself is exercised only by the gated E2E smoke.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from videogen.agent.gemini_review import GeminiReviewAgent, _parse_feedback
from videogen.agent.review import ReviewCategory, Severity
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, Composition, LayoutName, RegionName


def _composition() -> Composition:
    builder = Builder.new(
        voiceover="host", duration=2.0, assets={"host": Asset(type=AssetType.video, src="host.mp4")}
    )
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    return builder.composition


def test_parse_feedback_maps_points_spans_categories_and_severities() -> None:
    data = {
        "no_actionable_issues": False,
        "items": [
            {"at": 0.6, "category": "caption-sync", "severity": "blocking", "note": "late cue"},
            {"at": 1.0, "until": 2.0, "category": "framing", "severity": "suggestion", "note": "x"},
        ],
    }

    feedback = _parse_feedback(data)

    assert not feedback.no_actionable_issues
    first = feedback.items[0]
    assert first.at == 0.6 and first.until is None  # a point, not a span
    assert first.category is ReviewCategory.caption_sync and first.severity is Severity.blocking
    assert first.note == "late cue"
    second = feedback.items[1]
    assert second.until == 2.0 and second.category is ReviewCategory.framing
    assert second.severity is Severity.suggestion


def test_parse_feedback_reads_a_clean_pass() -> None:
    feedback = _parse_feedback({"no_actionable_issues": True, "items": []})

    assert feedback.no_actionable_issues and feedback.items == ()


class _FakeGenai:
    """A stand-in google-genai client: records the upload + generate calls, returns canned JSON."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.uploaded: str | None = None
        self.gen_kwargs: dict[str, Any] = {}
        self.files = SimpleNamespace(upload=self._upload, get=self._get)
        self.models = SimpleNamespace(generate_content=self._generate)

    def _upload(self, *, file: str) -> Any:
        self.uploaded = file
        return SimpleNamespace(name="files/abc", state=SimpleNamespace(name="ACTIVE"))

    def _get(self, *, name: str) -> Any:  # pragma: no cover - file is active on upload here
        return SimpleNamespace(name=name, state=SimpleNamespace(name="ACTIVE"))

    def _generate(self, **kwargs: Any) -> Any:
        self.gen_kwargs = kwargs
        return SimpleNamespace(text=json.dumps(self._payload))


def test_review_uploads_the_video_generates_and_returns_parsed_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pin the Developer-API (files.upload) branch: with Vertex/ADC active in the env, review reads the
    # bytes inline and never uploads, which the upload-only fake can't model.
    monkeypatch.setattr("videogen.genai_client.use_vertex_adc", lambda: False)
    video = tmp_path / "render.mp4"
    video.write_bytes(b"fake-mp4")
    client = _FakeGenai(
        {"no_actionable_issues": False, "items": [
            {"at": 0.5, "category": "pacing", "severity": "blocking", "note": "rushed cut"}
        ]}
    )
    agent = GeminiReviewAgent(model="gemini-2.5-flash", client=client)

    feedback = agent.review(video=video, composition=_composition(), timeline="0-2s host")

    assert client.uploaded == str(video)  # the rendered mp4 was handed to the model
    assert client.gen_kwargs["model"] == "gemini-2.5-flash"
    assert feedback.items[0].category is ReviewCategory.pacing
    assert feedback.items[0].note == "rushed cut"
