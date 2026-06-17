"""MediaService: ingest, probe, transcribe, resolve -- facts only, ADR 0003 (Phases 2-3).

MediaService is the single place that knows where media bytes live on disk and the only producer
of objective media facts (duration, dimensions, frame rate, and -- from Phase 3 -- a word-level
transcript). It holds no creative state. v1 is an in-process implementation backed by filesystem
paths; `resolve` is the seam an S3-backed store would later replace without touching callers.

`transcribe` runs faster-whisper with `word_timestamps=True` against the host recording's audio --
the voiceover and master clock (ADR 0005) -- and returns per-word start/end times in seconds, the
unit the Timeline keeps canonical. It produces an objective fact only: it never groups words into
captions or picks a style (ADR 0003); that is the authoring Agent's job (Phase 8), and the word
timings are what a future Media Manifest will surface for it to perceive. faster-whisper is an
optional dependency (heavy native runtime + a downloaded model); install it with
`uv sync --extra transcribe`. It is imported lazily so ingest/probe/resolve stay available without
it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videogen.kernel.composition import AssetId

_CHUNK = 1 << 20  # 1 MiB; hash the file in chunks so large recordings stay out of memory


@dataclass(frozen=True)
class ProbeResult:
    """Objective facts about a recording. No creative interpretation (ADR 0003)."""

    duration: float  # seconds
    width: int  # pixels
    height: int  # pixels
    fps: float  # frames per second


@dataclass(frozen=True)
class Word:
    """One transcribed word with its start/end on the absolute-seconds Timeline (ADR 0005)."""

    text: str
    start: float  # seconds
    end: float  # seconds


@dataclass(frozen=True)
class Transcript:
    """A word-level transcript: an ordered list of Words. The objective fact captions hang off."""

    words: list[Word]

    @property
    def text(self) -> str:
        """The full utterance, words joined by spaces."""
        return " ".join(word.text for word in self.words)


# A loaded faster-whisper model is expensive to construct; cache one per (size, compute) across
# the process so repeated transcribe calls (and tests) reuse it.
_WHISPER_MODELS: dict[tuple[str, str], Any] = {}


class MediaService:
    """In-process MediaService for v1: ingest a recording, probe its facts, resolve id -> path."""

    def __init__(self) -> None:
        self._paths: dict[AssetId, Path] = {}

    def ingest(self, path: str | Path) -> AssetId:
        """Register a recording and return a stable Asset id (content hash).

        The same bytes always yield the same id, so the rest of the pipeline refers to media by
        id and never by raw path.
        """
        resolved = Path(path).resolve()
        asset_id = f"asset-{self._content_hash(resolved)}"
        self._paths[asset_id] = resolved
        return asset_id

    def resolve(self, asset_id: AssetId) -> Path:
        """Map an Asset id back to its on-disk path. Raises KeyError if unknown."""
        return self._paths[asset_id]

    def probe(self, asset_id: AssetId) -> ProbeResult:
        """Probe a recording with ffprobe and return objective facts."""
        return _ffprobe(self.resolve(asset_id))

    def transcribe(
        self,
        asset_id: AssetId,
        *,
        model_size: str = "base",
        language: str | None = None,
    ) -> Transcript:
        """Transcribe a recording's audio to a word-level Transcript (faster-whisper, ADR 0005).

        Always targets the recording's own audio: callers pass the host recording's Asset id, whose
        audio is the voiceover. `word_timestamps=True` yields per-word start/end times, returned in
        seconds so they slot straight onto the Timeline. This is an objective fact only -- no word
        grouping, no style choice (ADR 0003).
        """
        model = _load_whisper(model_size)
        segments, _info = model.transcribe(
            str(self.resolve(asset_id)), word_timestamps=True, language=language
        )
        words: list[Word] = []
        for segment in segments:  # faster-whisper streams segments lazily; iterating runs the model
            for word in segment.words or ():
                words.append(
                    Word(text=word.word.strip(), start=float(word.start), end=float(word.end))
                )
        return Transcript(words=words)

    @staticmethod
    def _content_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()[:12]


def _ffprobe(path: Path) -> ProbeResult:
    """Run ffprobe and extract duration, dimensions, and frame rate from the first video stream."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found on PATH; install ffmpeg to probe media")
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(proc.stdout)
    stream = data["streams"][0]
    fmt = data.get("format", {})
    raw_dur = fmt.get("duration")
    return ProbeResult(
        duration=float(raw_dur) if raw_dur is not None else 0.0,
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=_parse_fraction(stream["r_frame_rate"]),
    )


def _parse_fraction(value: str) -> float:
    """ffprobe reports frame rate as a rational like '30/1'; turn it into a float."""
    num, _, den = value.partition("/")
    return float(num) / float(den) if den else float(num)


def _load_whisper(model_size: str, compute_type: str = "int8") -> Any:
    """Load (and cache) a faster-whisper model. Raises a clear error if the optional dep is absent.

    Runs on CPU with int8 quantization -- fast enough for short host clips and dependency-free of a
    GPU. The first construction downloads the model weights; later calls reuse the cached instance.
    """
    key = (model_size, compute_type)
    if key not in _WHISPER_MODELS:
        try:
            from faster_whisper import WhisperModel
        except ModuleNotFoundError as exc:  # optional dependency
            raise RuntimeError(
                "transcription needs faster-whisper; install it with "
                "`uv sync --extra transcribe`"
            ) from exc
        _WHISPER_MODELS[key] = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    return _WHISPER_MODELS[key]
