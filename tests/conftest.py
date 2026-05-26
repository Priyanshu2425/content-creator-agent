"""Shared fixtures for the render path.

The host-recording fixture is a small, deterministic clip generated once per session with
ffmpeg: 9:16, 30fps, ~2s, color bars (bright, non-black) plus a sine tone so it carries both a
video stream and an audio stream -- the shape of a real host-cam recording (ADR 0005). Tests
that need a recording probe and render this rather than checking in a binary asset.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Composition,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)

HOST_DURATION = 2.0
HOST_WIDTH = 1080
HOST_HEIGHT = 1920
HOST_FPS = 30

_have_ffmpeg = shutil.which("ffmpeg") is not None


@pytest.fixture(scope="session")
def host_only_composition() -> Callable[..., Composition]:
    """Factory for the canonical host-only Composition (ADR 0001/0005 at smallest valid size).

    One video Asset, a voiceover pointing at that same recording's audio (the master clock), and
    exactly one `full` Scene whose single `full` Region references the host. No overlays, no
    captions, no transitions. Callers vary `src` (a stable name for the snapshot, a real path for
    the render) and `duration` (the probed voiceover length).
    """

    def make(src: str, duration: float, asset_id: str = "host") -> Composition:
        return Composition(
            assets={asset_id: Asset(type=AssetType.video, src=src)},
            voiceover=Audio(asset=asset_id),
            scenes=[
                Scene(
                    id="s0",
                    start=0.0,
                    end=duration,
                    layout=LayoutName.full,
                    regions={RegionName.full: Ref(asset=asset_id)},
                )
            ],
        )

    return make


@pytest.fixture(scope="session")
def host_facts() -> dict[str, float]:
    """The objective facts the generated host recording is built to have."""
    return {
        "duration": HOST_DURATION,
        "width": HOST_WIDTH,
        "height": HOST_HEIGHT,
        "fps": HOST_FPS,
    }


@pytest.fixture(scope="session")
def host_recording(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A generated host-cam recording (video + audio) on disk; the canonical Phase 2 input."""
    if not _have_ffmpeg:
        pytest.skip("ffmpeg not on PATH")
    out = tmp_path_factory.mktemp("media") / "host.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={HOST_WIDTH}x{HOST_HEIGHT}:rate={HOST_FPS}:duration={HOST_DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={HOST_DURATION}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out
