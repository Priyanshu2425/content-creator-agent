"""Render path (integration): host recording -> IR -> RemotionBackend -> mp4 / still.

This is the seam Phase 2 de-risked -- the Python <-> Remotion <-> IR boundary -- now carrying
captions (the Phase 3 MVP). The tests assert external, observable behavior of the render path, not
subprocess internals: the file exists, its duration is approximately the host length (a tolerance,
because container rounding and frame quantization shift the last fraction of a second), a sampled
frame is non-black, and captions appear on time and disappear in the gaps.

Caption content is checked by diffing the captioned render against a host-only render of the same
recording: at a caption's time the frames differ (the caption was painted), in a gap they are
identical (nothing was). This isolates the caption signal from whatever footage is underneath, so
the assertions stay behavioral and background-agnostic rather than pixel-perfect (which would be
brittle across Remotion and codec versions). The MVP acceptance test goes further on a real spoken
clip: words are transcribed, mapped onto captions in all three styles, rendered, and checked for
on-time presence, the kinetic pop-in, and the pill's distinguishing dark band.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.backends.remotion import RemotionBackend
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Caption, CaptionStyle, Composition
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
requires_whisper = pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is None,
    reason="needs faster-whisper (uv sync --extra transcribe)",
)

# Styles cycle across transcript words so the MVP exercises all three in one render.
_STYLE_CYCLE = [CaptionStyle.pill, CaptionStyle.word_bold, CaptionStyle.kinetic]


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def _gray_frame(path: Path, at: float) -> bytes:
    """Raw grayscale pixels of the frame at time `at` (frame-accurate: `-ss` after `-i`)."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ss", str(at),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    )
    assert proc.stdout, "ffmpeg returned no pixels for the sampled frame"
    return proc.stdout


def _mean_luma(path: Path, at: float) -> float:
    """Mean grayscale value of one frame at time `at`."""
    pixels = _gray_frame(path, at)
    return sum(pixels) / len(pixels)


def _changed_fraction(a: Path, b: Path, at: float, thr: int = 30) -> float:
    """Fraction of pixels that differ by more than `thr` between two renders at the same time.

    The two renders share identical footage and differ only in captions, so this measures how much
    caption was painted at `at` -- high where a caption shows, ~0 where none does. `thr` ignores the
    small per-pixel jitter of independent codec passes.
    """
    pa, pb = _gray_frame(a, at), _gray_frame(b, at)
    assert len(pa) == len(pb), "frames differ in size; cannot diff"
    changed = sum(1 for x, y in zip(pa, pb, strict=True) if abs(x - y) > thr)
    return changed / len(pa)


def _lower_region(path: Path, at: float) -> bytes:
    """Raw grayscale pixels of the lower third (where captions sit) at time `at`."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ss", str(at),
         "-frames:v", "1", "-vf", "crop=iw:ih*3/10:0:ih*7/10",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    )
    assert proc.stdout, "ffmpeg returned no pixels for the caption region"
    return proc.stdout


def _dark_fraction(pixels: bytes, thr: int = 80) -> float:
    """Fraction of pixels darker than `thr` -- the signature of the pill's dark background band."""
    return sum(1 for p in pixels if p < thr) / len(pixels)


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


# --- captions over the host footage (Phase 3) ---


@pytest.fixture
def host_captioned_ir(
    host_recording: Path,
    host_captions_composition: Callable[..., Composition],
) -> object:
    """The captioned IR for the same host recording `host_ir` uses, so the two can be diffed."""
    service = MediaService()
    asset_id = service.ingest(host_recording)
    facts = service.probe(asset_id)
    comp = host_captions_composition(src=str(service.resolve(asset_id)), duration=facts.duration)
    return compile_ir(comp, fps=round(facts.fps), duration=facts.duration)


@requires_toolchain
def test_captions_are_painted_on_time_over_the_host_footage(
    host_ir: object,
    host_captioned_ir: object,
    caption_specs: list[tuple[str, float, float, CaptionStyle]],
    tmp_path: Path,
) -> None:
    backend = RemotionBackend()
    plain = backend.render_video(host_ir, tmp_path / "plain.mp4")  # type: ignore[arg-type]
    capped = backend.render_video(host_captioned_ir, tmp_path / "capped.mp4")  # type: ignore[arg-type]

    assert capped.exists() and capped.stat().st_size > 0
    # Captions are additive: they must not change the composition's length (master clock, ADR 0005).
    assert abs(_probe_duration(capped) - _probe_duration(plain)) < 0.2

    # In the caption-free lead the renders are identical; nothing is painted before the first cue.
    assert _changed_fraction(capped, plain, at=0.05) < 0.001

    # At each caption's mid-time the captioned render diverges -- the cue landed on time. The
    # margin clears the measured 0.000 of a gap with room while admitting a single small word.
    for _text, start, end, _style in caption_specs:
        mid = (start + end) / 2
        assert _changed_fraction(capped, plain, at=mid) > 0.001, f"no caption painted near t={mid}"


@requires_toolchain
@requires_whisper
def test_mvp_real_clip_renders_on_time_styled_captions(
    spoken_recording: Path, tmp_path: Path
) -> None:
    """MVP acceptance: a real spoken clip -> word-synced, correctly-styled captions in an mp4.

    Transcribes the clip, maps the words onto captions cycling through all three styles, renders
    the captioned mp4 and a caption-free reference, and checks the milestone behavior: captions are
    present at their words and absent in the silence, the kinetic word pops in (animates up), and
    the pill caption shows its distinguishing dark band while the word-bold one does not.
    """
    service = MediaService()
    asset_id = service.ingest(spoken_recording)
    duration = service.probe(asset_id).duration
    words = service.transcribe(asset_id).words
    if len(words) < 3:
        pytest.skip(f"transcription yielded too few words ({len(words)}) to style three captions")

    captions = [
        Caption(text=w.text, start=w.start, end=w.end, style=_STYLE_CYCLE[i % len(_STYLE_CYCLE)])
        for i, w in enumerate(words)
    ]
    comp = Composition.model_validate(
        {
            "assets": {"host": {"type": "video", "src": str(service.resolve(asset_id))}},
            "voiceover": {"asset": "host"},
            "scenes": [
                {"id": "s0", "start": 0.0, "end": duration, "layout": "full",
                 "regions": {"full": {"asset": "host"}}}
            ],
            "captions": [c.model_dump(by_alias=True) for c in captions],
        }
    )
    ir = compile_ir(comp, fps=30, duration=duration)
    ir_plain = compile_ir(comp.model_copy(update={"captions": []}), fps=30, duration=duration)

    backend = RemotionBackend()
    capped = backend.render_video(ir, tmp_path / "mvp.mp4")
    plain = backend.render_video(ir_plain, tmp_path / "mvp_plain.mp4")

    assert capped.exists() and abs(_probe_duration(capped) - duration) < 0.3

    pill = next(c for c in captions if c.style is CaptionStyle.pill)
    bold = next(c for c in captions if c.style is CaptionStyle.word_bold)
    kinetic = next(c for c in captions if c.style is CaptionStyle.kinetic)

    # On time: each word's caption shows at the word, and the trailing silence carries none. (The
    # gap is taken after the last caption -- recognizers don't reliably honor leading silence.)
    last_end = max(c.end for c in captions)
    assert last_end < duration, "no trailing silence to assert a caption-free gap against"
    gap = (last_end + duration) / 2
    assert _changed_fraction(capped, plain, at=gap) < 0.001, f"caption in the gap at t={gap}"
    for cap in (pill, bold, kinetic):
        mid = (cap.start + cap.end) / 2
        assert _changed_fraction(capped, plain, at=mid) > 0.001, f"caption missing at t={mid}"

    # Kinetic pops in: far less is painted at the very start of its span than mid-span.
    assert _changed_fraction(capped, plain, at=kinetic.start + 0.005) < _changed_fraction(
        capped, plain, at=(kinetic.start + kinetic.end) / 2
    )

    # Styled correctly: the pill shows its dark background band; the plain word-bold does not.
    pill_dark = _dark_fraction(_lower_region(capped, (pill.start + pill.end) / 2))
    bold_dark = _dark_fraction(_lower_region(capped, (bold.start + bold.end) / 2))
    assert pill_dark > bold_dark + 0.01, f"pill band not distinct ({pill_dark=} {bold_dark=})"
