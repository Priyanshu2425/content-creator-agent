"""MediaService: ingest, probe, transcribe, resolve -- facts only, ADR 0003 (Phases 2-3).

MediaService is the single place that knows where media bytes live on disk and the only producer
of objective media facts (duration, dimensions, frame rate). It holds no creative state. v1 is an
in-process implementation backed by filesystem paths; `resolve` is the seam an S3-backed store
would later replace without touching callers. `transcribe` is named in the service shape but is
not implemented until Phase 3.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videogen.kernel.composition import AssetId

_CHUNK = 1 << 20  # 1 MiB; hash the file in chunks so large recordings stay out of memory


@dataclass(frozen=True)
class ProbeResult:
    """Objective facts about a recording. No creative interpretation (ADR 0003)."""

    duration: float  # seconds
    width: int  # pixels
    height: int  # pixels
    fps: float  # frames per second


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

    def transcribe(self, asset_id: AssetId) -> object:
        """Word-level transcription. Deferred to Phase 3."""
        raise NotImplementedError("transcription arrives in Phase 3")

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
    return ProbeResult(
        duration=float(data["format"]["duration"]),
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=_parse_fraction(stream["r_frame_rate"]),
    )


def _parse_fraction(value: str) -> float:
    """ffprobe reports frame rate as a rational like '30/1'; turn it into a float."""
    num, _, den = value.partition("/")
    return float(num) / float(den) if den else float(num)
