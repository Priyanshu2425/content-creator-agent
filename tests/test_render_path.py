"""Render path (integration): host recording -> IR -> RemotionBackend -> mp4 / still.

This is the seam Phase 2 exists to de-risk -- the Python <-> Remotion <-> IR boundary. The tests
assert external, observable behavior of the render path, not the internals of the subprocess
invocation: the file exists, its duration is approximately the host length (a tolerance, because
container rounding and frame quantization shift the last fraction of a second), and a sampled
frame is non-black (the cheapest meaningful proof real footage reached the frames). The still
test mirrors the video assertion at a single frame, proving the in-loop vision channel Phase 8
will depend on.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.backends.remotion import RemotionBackend
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Composition
from videogen.services.media import MediaService

pytestmark = pytest.mark.integration

_PROJECT = Path("src/videogen/backends/remotion/project")
_toolchain_ready = (
    shutil.which("npx") is not None
    and shutil.which("ffmpeg") is not None
    and (_PROJECT / "node_modules" / ".bin" / "remotion").exists()
)
requires_toolchain = pytest.mark.skipif(
    not _toolchain_ready, reason="needs npx + ffmpeg + installed Remotion node deps"
)


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def _mean_luma(path: Path, at: float) -> float:
    """Mean grayscale value of one frame at time `at`, via ffmpeg raw output (no Pillow needed)."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    )
    pixels = proc.stdout
    assert pixels, "ffmpeg returned no pixels for the sampled frame"
    return sum(pixels) / len(pixels)


@pytest.fixture
def host_ir(
    host_recording: Path,
    host_only_composition: Callable[..., Composition],
) -> object:
    service = MediaService()
    asset_id = service.ingest(host_recording)
    facts = service.probe(asset_id)
    comp = host_only_composition(
        src=str(service.resolve(asset_id)), duration=facts.duration
    )
    return compile_ir(comp, fps=round(facts.fps), duration=facts.duration)


@requires_toolchain
def test_render_video_produces_a_non_black_talking_head(
    host_ir: object, host_recording: Path, tmp_path: Path
) -> None:
    out = RemotionBackend().render_video(host_ir, tmp_path / "out.mp4")  # type: ignore[arg-type]

    assert out.exists() and out.stat().st_size > 0
    expected = _probe_duration(host_recording)
    assert abs(_probe_duration(out) - expected) < 0.3  # nothing silently truncated or padded
    assert _mean_luma(out, at=1.0) > 5.0  # real footage reached the frames, not an empty canvas


@requires_toolchain
def test_render_still_produces_a_non_black_frame(host_ir: object, tmp_path: Path) -> None:
    out = RemotionBackend().render_still(host_ir, 1.0, tmp_path / "still.png")  # type: ignore[arg-type]

    assert out.exists() and out.stat().st_size > 0
    assert _mean_luma(out, at=0.0) > 5.0
