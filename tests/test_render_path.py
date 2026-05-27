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
from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import (
    Anchor,
    Asset,
    AssetType,
    Caption,
    CaptionStyle,
    Composition,
    InsertOverlay,
    LayoutName,
    RegionName,
    ZoomOverlay,
)
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
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(proc.stdout.strip())


def _gray_frame(path: Path, at: float) -> bytes:
    """Raw grayscale pixels of the frame at time `at` (frame-accurate: `-ss` after `-i`)."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(at),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
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
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(at),
            "-frames:v",
            "1",
            "-vf",
            "crop=iw:ih*3/10:0:ih*7/10",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
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
    comp = host_only_composition(src=str(service.resolve(asset_id)), duration=facts.duration)
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
                {
                    "id": "s0",
                    "start": 0.0,
                    "end": duration,
                    "layout": "full",
                    "regions": {"full": {"asset": "host"}},
                }
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


# --- multi-scene with a b-roll cut (Phase 5) ---


@pytest.fixture
def broll_card(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bright solid-color still standing in for a screenshot/clip cut to full-frame as b-roll."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    out = tmp_path_factory.mktemp("broll") / "card.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xE03030:size=1080x1920",
            "-frames:v",
            "1",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


@requires_toolchain
def test_multi_scene_with_a_broll_cut_renders_a_full_length_non_black_mp4(
    host_recording: Path, broll_card: Path, tmp_path: Path
) -> None:
    """The reference-video b-roll form: a full host Scene cutting to a full-frame b-roll Scene.

    Authored through the Phase 4/5 Builder, compiled via the registry, and rendered end to end. The
    voiceover (the host recording's audio) plays straight through the cut as the master clock, so
    the mp4 is the host's length; both the host half and the b-roll half sample non-black.
    """
    service = MediaService()
    host_id = service.ingest(host_recording)
    facts = service.probe(host_id)
    duration = facts.duration
    cut = duration / 2

    builder = Builder.new(
        voiceover="host",
        duration=duration,
        assets={
            "host": Asset(type=AssetType.video, src=str(service.resolve(host_id))),
            "broll": Asset(type=AssetType.image, src=str(broll_card)),
        },
    )
    builder.add_scene(LayoutName.full, 0.0, cut, id="host")
    builder.fill_region("host", RegionName.full, "host")
    builder.add_scene(LayoutName.full, cut, duration, id="broll")
    builder.fill_region("broll", RegionName.full, "broll")
    assert builder.can_submit_render()

    ir = compile_ir(builder.composition, fps=round(facts.fps), duration=duration)
    out = RemotionBackend().render_video(ir, tmp_path / "broll_cut.mp4")

    assert out.exists() and out.stat().st_size > 0
    assert abs(_probe_duration(out) - duration) < 0.3  # voiceover length, through the cut
    assert _mean_luma(out, at=cut * 0.5) > 5.0  # host half is on screen
    assert _mean_luma(out, at=cut + (duration - cut) * 0.5) > 5.0  # b-roll card is on screen


def _half_gray(path: Path, at: float, *, bottom: bool) -> bytes:
    """Raw grayscale pixels of the top or bottom half of the frame at time `at`."""
    crop = "crop=iw:ih/2:0:ih/2" if bottom else "crop=iw:ih/2:0:0"
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(at),
            "-frames:v",
            "1",
            "-vf",
            crop,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    assert proc.stdout
    return proc.stdout


@requires_toolchain
def test_split_h_places_its_two_regions_in_the_top_and_bottom_halves(
    host_recording: Path, broll_card: Path, tmp_path: Path
) -> None:
    """The split-screen hook: a split-h Scene with the host on top and a b-roll card on the bottom.

    Renders a still and compares the bottom half against a full-host still of the same recording:
    the bottom diverges sharply (the solid card replaced the host there), proving the preset's
    geometry positioned the bottom Region -- the rect reached the backend and placed it (ADR 0001).
    """
    service = MediaService()
    host_id = service.ingest(host_recording)
    facts = service.probe(host_id)
    duration = facts.duration
    host_src = str(service.resolve(host_id))

    builder = Builder.new(
        voiceover="host",
        duration=duration,
        assets={
            "host": Asset(type=AssetType.video, src=host_src),
            "broll": Asset(type=AssetType.image, src=str(broll_card)),
        },
    )
    builder.add_scene(LayoutName.split_h, 0.0, duration, id="hook")
    builder.fill_region("hook", RegionName.top, "host")
    builder.fill_region("hook", RegionName.bottom, "broll")
    assert builder.can_submit_render()
    split_ir = compile_ir(builder.composition, fps=round(facts.fps), duration=duration)

    full_builder = Builder.new(
        voiceover="host",
        duration=duration,
        assets={"host": Asset(type=AssetType.video, src=host_src)},
    )
    full_builder.add_scene(LayoutName.full, 0.0, duration, id="s0")
    full_builder.fill_region("s0", RegionName.full, "host")
    full_ir = compile_ir(full_builder.composition, fps=round(facts.fps), duration=duration)

    backend = RemotionBackend()
    split = backend.render_still(split_ir, 0.5, tmp_path / "split.png")
    full = backend.render_still(full_ir, 0.5, tmp_path / "full.png")

    def changed(a: bytes, b: bytes, thr: int = 30) -> float:
        return sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) > thr) / len(a)

    # The stills are single-frame PNGs, so they are read back at t=0. The bottom half is the solid
    # card in the split but the host in the full render: it differs a lot. The top half is the host
    # in both, so it changes far less than the bottom.
    bottom_diff = changed(_half_gray(split, 0.0, bottom=True), _half_gray(full, 0.0, bottom=True))
    top_diff = changed(_half_gray(split, 0.0, bottom=False), _half_gray(full, 0.0, bottom=False))
    assert bottom_diff > 0.5, f"bottom region not placed ({bottom_diff=})"
    assert bottom_diff > top_diff


# --- effects: zoom + insert over the host footage (Phase 6) ---


@requires_toolchain
def test_effects_render_full_length_and_the_still_agrees_with_the_video_mid_effect(
    host_recording: Path, broll_card: Path, tmp_path: Path
) -> None:
    """A host Scene carrying a slow zoom (transform) and a floating insert (additive), end to end.

    The effects render is diffed against an effect-free render of the same footage: at a sampled
    instant the two differ (the zoom reshaped the frame and the insert painted a card over it),
    while the master-clock duration is unchanged (effects are additive to the timeline, ADR 0005).
    A `render_still` at the same instant diverges from a plain still the same way -- the still and
    the video sample the same interpolated effect state (the on-demand vision the agent relies on).
    """
    service = MediaService()
    host_id = service.ingest(host_recording)
    facts = service.probe(host_id)
    duration = facts.duration
    mid = duration / 2
    fps = round(facts.fps)

    builder = Builder.new(
        voiceover="host",
        duration=duration,
        assets={
            "host": Asset(type=AssetType.video, src=str(service.resolve(host_id))),
            "broll": Asset(type=AssetType.image, src=str(broll_card)),
        },
    )
    builder.add_scene(LayoutName.full, 0.0, duration, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    builder.add_overlay(
        ZoomOverlay(start=0.0, end=duration, target=RegionName.full, from_scale=1.0, to_scale=1.4)
    )
    builder.add_overlay(
        InsertOverlay(
            start=0.2,
            end=duration - 0.2,
            target=RegionName.full,
            asset="broll",
            anchor=Anchor.top_right,
            scale=0.3,
        )
    )
    assert builder.can_submit_render()

    comp = builder.composition
    ir = compile_ir(comp, fps=fps, duration=duration)
    plain_ir = compile_ir(comp.model_copy(update={"overlays": []}), fps=fps, duration=duration)

    backend = RemotionBackend()
    effects = backend.render_video(ir, tmp_path / "effects.mp4")
    plain = backend.render_video(plain_ir, tmp_path / "plain.mp4")

    assert effects.exists() and effects.stat().st_size > 0
    assert abs(_probe_duration(effects) - duration) < 0.3  # master clock unchanged by the effects
    assert _mean_luma(effects, at=mid) > 5.0  # a sampled mid-effect frame is non-black
    # The effects diverge from the plain render: the zoom and/or the insert painted into the frame.
    assert _changed_fraction(effects, plain, at=mid) > 0.001, "effects left no mark on the frame"

    # The still at the same instant samples the same effect state, diverging from a plain still too.
    still = backend.render_still(ir, mid, tmp_path / "still.png")
    plain_still = backend.render_still(plain_ir, mid, tmp_path / "plain_still.png")
    assert still.exists() and _mean_luma(still, at=0.0) > 5.0
    assert _changed_fraction(still, plain_still, at=0.0) > 0.001, "still did not reflect the effect"
