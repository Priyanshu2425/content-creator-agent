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

from videogen.agent.tools import DRAFT_OPS, DRAFT_TOOLS, TOOLS
from videogen.creation.base import AudioKind
from videogen.creation.elevenlabs import ElevenLabsAudioCreator
from videogen.creation.google import GoogleMediaCreator


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
