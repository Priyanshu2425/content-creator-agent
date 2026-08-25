"""Media creation providers (TODO 3 scaffolding): image/video via Google, audio via ElevenLabs.

The SDK calls and API keys are external, so these tests cover the part that is ours and
deterministic: each adapter translates a prompt + output path into the right SDK call and writes
the returned bytes (or byte stream) to disk. A fake SDK client is injected so the round trip is
verified without the real SDK, a key, or a network call. The providers are not wired into the
authoring loop yet; this pins their file-out contract.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from videogen.agent.tools import DRAFT_OPS, DRAFT_TOOLS, TOOLS
from videogen.creation.base import AudioKind
from videogen.creation.elevenlabs import ElevenLabsAudioCreator
from videogen.creation.google import GoogleMediaCreator
from videogen.creation.nano_banana import NanoBananaCreator


class _FakeImages:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def generate_images(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        image = SimpleNamespace(image_bytes=b"\x89PNG-fake")
        return SimpleNamespace(generated_images=[SimpleNamespace(image=image)])


def test_google_create_image_calls_imagen_and_writes_the_bytes(tmp_path: Path) -> None:
    images = _FakeImages()
    client = SimpleNamespace(models=images)
    creator = GoogleMediaCreator(client=client)

    out = creator.create_image(prompt="a neon city", out_path=tmp_path / "shot.png")

    assert out.read_bytes() == b"\x89PNG-fake"
    assert images.kwargs["prompt"] == "a neon city"
    assert images.kwargs["config"]["aspect_ratio"] == "9:16"


def test_google_create_video_polls_the_operation_then_writes(tmp_path: Path) -> None:
    video = SimpleNamespace(video_bytes=b"fake-mp4")

    class _Ops:
        def __init__(self) -> None:
            self.gets = 0

        def get(self, _operation: Any) -> Any:
            self.gets += 1
            return SimpleNamespace(  # second poll: done
                done=True,
                response=SimpleNamespace(generated_videos=[SimpleNamespace(video=video)]),
            )

    class _Models:
        def generate_videos(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(done=False)  # first: still running -> forces a poll

    ops = _Ops()
    client = SimpleNamespace(
        models=_Models(), operations=ops, files=SimpleNamespace(download=lambda file: None)
    )
    creator = GoogleMediaCreator(client=client)

    # zero the poll delay so the test doesn't actually sleep
    import videogen.creation.google as g

    original = g._POLL_SECONDS
    g._POLL_SECONDS = 0.0
    try:
        out = creator.create_video(prompt="a drone shot", out_path=tmp_path / "clip.mp4")
    finally:
        g._POLL_SECONDS = original

    assert out.read_bytes() == b"fake-mp4"
    assert ops.gets == 1  # polled once after the not-done first response


class _FakeImageGen:
    """Fake Nano Banana: records the generate_content kwargs, returns inline image bytes."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def generate_content(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNG-nano"))
        content = SimpleNamespace(parts=[part])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def test_nano_banana_create_image_writes_inline_bytes_with_aspect_ratio(tmp_path: Path) -> None:
    gen = _FakeImageGen()
    client = SimpleNamespace(models=gen)
    creator = NanoBananaCreator(model="gemini-2.5-flash-image", client=client)

    out = creator.create_image(
        prompt="bold stat card: 92%", out_path=tmp_path / "slot.png", aspect_ratio="9:16"
    )

    assert out.read_bytes() == b"\x89PNG-nano"
    assert gen.kwargs["model"] == "gemini-2.5-flash-image"
    assert gen.kwargs["contents"] == ["bold stat card: 92%"]
    assert gen.kwargs["config"]["response_modalities"] == ["IMAGE"]
    assert gen.kwargs["config"]["image_config"]["aspect_ratio"] == "9:16"


class _Flaky429:
    """Nano Banana fake that raises a 429 the first ``fail_times`` calls, then returns an image."""

    def __init__(self, fail_times: int) -> None:
        self.calls = 0
        self.fail_times = fail_times

    def generate_content(self, **_kwargs: Any) -> Any:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}")
        part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNG-nano"))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def test_nano_banana_retries_on_429_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import videogen.creation.nano_banana as nb

    monkeypatch.setattr(nb, "_RETRY_BASE_SECONDS", 0.0)  # no real sleep in the test
    gen = _Flaky429(fail_times=2)
    creator = NanoBananaCreator(client=SimpleNamespace(models=gen))

    out = creator.create_image(prompt="x", out_path=tmp_path / "s.png")

    assert out.read_bytes() == b"\x89PNG-nano"
    assert gen.calls == 3  # two 429s retried, third succeeds


def test_nano_banana_reraises_after_exhausting_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import videogen.creation.nano_banana as nb

    monkeypatch.setattr(nb, "_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(nb, "_MAX_ATTEMPTS", 3)
    gen = _Flaky429(fail_times=99)
    creator = NanoBananaCreator(client=SimpleNamespace(models=gen))

    with pytest.raises(Exception):  # noqa: B017 -- 429 propagates after the cap
        creator.create_image(prompt="x", out_path=tmp_path / "s.png")
    assert gen.calls == 3  # capped at _MAX_ATTEMPTS, not infinite


def test_nano_banana_logs_each_429_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every backoff is logged via ``media_retry`` so a rate-limited run is visibly retrying."""
    import videogen.creation.nano_banana as nb
    from videogen import log

    monkeypatch.setattr(nb, "_RETRY_BASE_SECONDS", 0.0)
    retries: list[dict] = []
    spy = SimpleNamespace(media_retry=lambda **kw: retries.append(kw))
    monkeypatch.setattr(log, "get", lambda: spy)

    gen = _Flaky429(fail_times=2)
    NanoBananaCreator(client=SimpleNamespace(models=gen)).create_image(
        prompt="x", out_path=tmp_path / "s.png"
    )

    assert len(retries) == 2  # two 429s -> two logged retries before the success
    assert retries[0]["attempt"] == 1 and retries[0]["max_attempts"] == nb._MAX_ATTEMPTS
    assert "nano-banana" in retries[0]["what"]


def test_nano_banana_does_not_retry_non_rate_limit_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import videogen.creation.nano_banana as nb

    monkeypatch.setattr(nb, "_RETRY_BASE_SECONDS", 0.0)

    class _Boom:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise ValueError("400 INVALID_ARGUMENT")

    gen = _Boom()
    creator = NanoBananaCreator(client=SimpleNamespace(models=gen))

    with pytest.raises(ValueError):
        creator.create_image(prompt="x", out_path=tmp_path / "s.png")
    assert gen.calls == 1  # a non-429 error is not retried


class _FakeTTS:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def convert(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return iter([b"aud", b"io"])  # streamed byte chunks


def test_elevenlabs_speech_streams_chunks_to_disk(tmp_path: Path) -> None:
    tts = _FakeTTS()
    client = SimpleNamespace(text_to_speech=tts)
    creator = ElevenLabsAudioCreator(client=client)

    out = creator.create_audio(prompt="hello world", out_path=tmp_path / "vo.mp3")

    assert out.read_bytes() == b"audio"  # both chunks concatenated
    assert tts.kwargs["text"] == "hello world"
    assert tts.kwargs["voice_id"]  # the default voice was supplied


def test_elevenlabs_routes_sfx_to_the_sound_effects_endpoint(tmp_path: Path) -> None:
    calls: list[str] = []

    def _convert(**_kwargs: Any) -> bytes:
        calls.append("sfx")
        return b"boom"

    client = SimpleNamespace(text_to_sound_effects=SimpleNamespace(convert=_convert))
    creator = ElevenLabsAudioCreator(client=client)

    out = creator.create_audio(prompt="explosion", out_path=tmp_path / "s.mp3", kind=AudioKind.sfx)

    assert out.read_bytes() == b"boom" and calls == ["sfx"]


def test_draft_tools_are_defined_but_not_advertised_to_the_agent() -> None:
    draft_names = {t.name for t in DRAFT_TOOLS}
    live_names = {t.name for t in TOOLS}

    assert draft_names == DRAFT_OPS  # the four scaffolded tools
    assert draft_names.isdisjoint(live_names)  # never offered alongside the active tools
