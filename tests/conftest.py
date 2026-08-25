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
    Caption,
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

# The canonical host-plus-captions fixture: one Caption per known style, timed within the host clip.
# (text, start, end, style). Shared by the IR snapshot and the render integration test so both agree
# on exactly what is captioned and when. A caption-free lead (< 0.2s) gives a gap to assert against.
CAPTION_SPECS: list[tuple[str, float, float, str]] = [
    ("hello there", 0.2, 0.8, "pill"),
    ("this", 0.9, 1.2, "word-bold"),
    ("matters", 1.3, 1.8, "kinetic"),
]

_have_ffmpeg = shutil.which("ffmpeg") is not None
_have_say = shutil.which("say") is not None

# A short phrase spoken into the MVP/transcription clips. Enough distinct words to map onto several
# captions; expected words are matched leniently (lowercased, tolerant of recognition variance).
SPOKEN_PHRASE = "hello world this is a kinetic caption test"
SPOKEN_LEAD = 0.4  # seconds of leading silence so there is a guaranteed caption-free gap at t<lead


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
def host_captions_composition(
    host_only_composition: Callable[..., Composition],
) -> Callable[..., Composition]:
    """The host-only Composition extended with one Caption per style (the MVP fixture).

    Builds on the Phase 2 host-only base so the MVP is tested against the established case, then
    adds the captions from CAPTION_SPECS on the dedicated `captions` track -- one `pill`,
    `word-bold`, and `kinetic` each. Captions keep their default high `z`, so they paint above the
    host media.
    """

    def make(src: str, duration: float, asset_id: str = "host") -> Composition:
        base = host_only_composition(src=src, duration=duration, asset_id=asset_id)
        return base.model_copy(
            update={
                "captions": [
                    Caption(text=text, start=start, end=end, style=style)
                    for text, start, end, style in CAPTION_SPECS
                ]
            }
        )

    return make


@pytest.fixture(scope="session")
def caption_specs() -> list[tuple[str, float, float, str]]:
    """The (text, start, end, style) of each caption in the host-plus-captions fixture."""
    return CAPTION_SPECS


@pytest.fixture(scope="session")
def spoken_meta() -> dict[str, object]:
    """The known phrase spoken into the MVP/transcription clip and its leading-silence offset."""
    return {"phrase": SPOKEN_PHRASE, "lead": SPOKEN_LEAD}


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


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


@pytest.fixture(scope="session")
def spoken_recording(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real spoken host clip for transcription/MVP: TTS speech over a flat-gray video.

    macOS `say` synthesizes the known phrase; ffmpeg delays it past a leading silence and muxes it
    onto a mid-gray background sized like a host recording. The flat-gray base makes caption
    content cleanly separable in the MVP frame checks (white text and the pill's dark band both
    stand out against gray), and the leading silence guarantees a caption-free gap to assert
    against. Skips when `say`/`ffmpeg` are unavailable (non-macOS / no ffmpeg).
    """
    if not (_have_say and _have_ffmpeg):
        pytest.skip("needs macOS `say` + ffmpeg to synthesize a spoken clip")
    media = tmp_path_factory.mktemp("spoken")
    speech = media / "speech.aiff"
    subprocess.run(["say", "-o", str(speech), SPOKEN_PHRASE], check=True, capture_output=True)

    speech_dur = _probe_duration(speech)
    total = SPOKEN_LEAD + speech_dur + 0.3  # leading + trailing caption-free silence
    out = media / "spoken.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i",
            f"color=c=0x808080:size={HOST_WIDTH}x{HOST_HEIGHT}:rate={HOST_FPS}:duration={total}",
            "-i", str(speech),
            "-af", f"adelay={int(SPOKEN_LEAD * 1000)}:all=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(out),
        ],
        check=True, capture_output=True,
    )
    return out
