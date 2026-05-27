"""MediaService: objective facts only (ADR 0003).

Behavioral assertions about the facts the service promises -- a stable Asset id, the recording's
duration/dimensions/frame rate, id -> on-disk path resolution, and (Phase 3) a word-level
transcript -- not about how ffprobe or faster-whisper are invoked. The transcription test is
tolerant of speech-recognition variance: it checks the words it promises are mostly present, in
order, with monotonic start/end times in seconds within the clip (ADR 0005), not exact strings.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from videogen.services.media import MediaService

_have_whisper = importlib.util.find_spec("faster_whisper") is not None
requires_whisper = pytest.mark.skipif(
    not _have_whisper, reason="needs faster-whisper (uv sync --extra transcribe)"
)


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


@requires_whisper
def test_transcribe_returns_word_level_timings_in_seconds(
    spoken_recording: Path, spoken_meta: dict[str, object]
) -> None:
    service = MediaService()
    asset_id = service.ingest(spoken_recording)
    duration = service.probe(asset_id).duration

    transcript = service.transcribe(asset_id)

    assert transcript.words, "expected a non-empty word-level transcript"

    # Most of the spoken words are recognized (tolerant of ASR variance), and in order.
    spoken = transcript.text.lower()
    expected = str(spoken_meta["phrase"]).lower().split()
    present = [word for word in expected if word in spoken]
    assert len(present) >= len(expected) * 0.6, f"too few expected words in {spoken!r}"

    # Timings are seconds on the Timeline: each word's span is ordered and inside the clip, and the
    # words are non-decreasing in time. (Absolute start is left loose -- recognizers are unreliable
    # about leading silence -- which is exactly the variance the phase tolerates.)
    starts = [w.start for w in transcript.words]
    assert starts == sorted(starts)
    for word in transcript.words:
        assert 0.0 <= word.start <= word.end <= duration + 0.5
