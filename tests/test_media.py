"""MediaService: objective facts only (ADR 0003).

Behavioral assertions about the facts the service promises -- a stable Asset id, the recording's
duration/dimensions/frame rate, and id -> on-disk path resolution -- not about how ffprobe is
invoked. Transcription is Phase 3 and is asserted absent here.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from videogen.services.media import MediaService


def test_ingest_returns_stable_id(host_recording: Path) -> None:
    service = MediaService()
    first = service.ingest(host_recording)
    second = service.ingest(host_recording)
    assert first == second  # same bytes -> same id, so the pipeline can refer to media by id


def test_resolve_maps_id_to_on_disk_path(host_recording: Path) -> None:
    service = MediaService()
    asset_id = service.ingest(host_recording)
    assert service.resolve(asset_id) == host_recording.resolve()


def test_probe_returns_objective_facts(
    host_recording: Path, host_facts: dict[str, float]
) -> None:
    service = MediaService()
    asset_id = service.ingest(host_recording)
    facts = service.probe(asset_id)
    assert math.isclose(facts.duration, host_facts["duration"], abs_tol=0.2)
    assert facts.width == host_facts["width"]
    assert facts.height == host_facts["height"]
    assert math.isclose(facts.fps, host_facts["fps"], abs_tol=0.01)


def test_resolve_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        MediaService().resolve("asset-does-not-exist")


def test_transcribe_is_deferred_to_phase_3(host_recording: Path) -> None:
    service = MediaService()
    asset_id = service.ingest(host_recording)
    with pytest.raises(NotImplementedError):
        service.transcribe(asset_id)
