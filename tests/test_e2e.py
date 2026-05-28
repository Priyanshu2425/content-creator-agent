"""E2E smoke (Phase 9): `videogen make` over the whole wired pipeline -> a completed mp4.

The headline Phase 9 deliverable. It runs the real command body -- ingest + probe + transcribe
(MediaService), author + finalize through the video-review gate (AuthoringService + the live
models), and async render (RenderService via the adapter) -- against a generated host clip, one
b-roll still, and a short brief. It asserts the observable outcome the plan prescribes: a video
file is produced, the render job completes, the output duration is approximately the host length
(voiceover is the master clock, ADR 0005), and a sampled frame is non-black.

Because it invokes the real authoring and review models, it is gated on the relevant API keys (and
the SDKs, ffmpeg, faster-whisper, and the installed Remotion node deps) and kept out of the fast
deterministic suite. It skips cleanly when any prerequisite is absent.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from videogen.app.cli import Pipeline
from videogen.services.media import MediaService

pytestmark = pytest.mark.integration

_PROJECT = Path("src/videogen/backends/remotion/project")
_toolchain_ready = (
    shutil.which("npx") is not None
    and shutil.which("ffmpeg") is not None
    and (_PROJECT / "node_modules" / ".bin" / "remotion").exists()
)
_have_whisper = importlib.util.find_spec("faster_whisper") is not None
_have_anthropic = importlib.util.find_spec("anthropic") is not None
_have_genai = importlib.util.find_spec("google.genai") is not None
_have_anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
_have_gemini_key = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))

requires_everything = pytest.mark.skipif(
    not (
        _toolchain_ready
        and _have_whisper
        and _have_anthropic
        and _have_genai
        and _have_anthropic_key
        and _have_gemini_key
    ),
    reason="needs ffmpeg + Remotion deps + faster-whisper + anthropic + google-genai + API keys",
)


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def _mean_luma(path: Path, at: float) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ss", str(at), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    )
    assert proc.stdout, "ffmpeg returned no pixels for the sampled frame"
    return sum(proc.stdout) / len(proc.stdout)


@pytest.fixture
def broll_still(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bright solid-color still standing in for a screenshot passed as b-roll."""
    out = tmp_path_factory.mktemp("broll") / "card.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0xE03030:size=1080x1920",
         "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return out


@requires_everything
def test_make_produces_a_completed_mp4_from_host_broll_and_a_brief(
    host_recording: Path, broll_still: Path, tmp_path: Path
) -> None:
    from videogen.agent.clients import AnthropicModelClient
    from videogen.agent.gemini_review import GeminiReviewAgent
    from videogen.backends.remotion import RemotionBackend
    from videogen.services.authoring import AuthoringService
    from videogen.services.render import RenderService, RenderServiceRenderer
    from videogen.stores.blobs import FilesystemBlobStore

    backend = RemotionBackend()
    render_service = RenderService(backend=backend, blobs=FilesystemBlobStore(tmp_path / "renders"))
    pipeline = Pipeline(
        media=MediaService(),
        authoring=AuthoringService(backend=backend),
        renderer=RenderServiceRenderer(render_service),
        model_client=AnthropicModelClient(),
        reviewer=GeminiReviewAgent(),
    )

    try:
        out = pipeline.run(
            host=str(host_recording),
            broll=[str(broll_still)],
            brief="A short talking-head clip; cut to the b-roll near the end; add captions.",
        )
    finally:
        pipeline.close()

    artifact = Path(out)
    assert artifact.exists() and artifact.stat().st_size > 0  # the job completed with a real file
    expected = _probe_duration(host_recording)
    assert abs(_probe_duration(artifact) - expected) < 0.5  # voiceover is the master clock
    assert _mean_luma(artifact, at=1.0) > 5.0  # real footage reached the frames, not a black canvas
