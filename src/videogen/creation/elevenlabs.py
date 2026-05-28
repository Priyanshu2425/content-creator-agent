"""ElevenLabsAudioCreator: voiceover / sound-effect / music creation via the ElevenLabs SDK.

Implements the ``AudioCreator`` seam. ElevenLabs is audio-only (it has no image or video
generation), so it backs exactly the audio side of creation: ``speech`` (text-to-speech),
``sfx`` (text-to-sound-effects), and ``music`` (text-to-music). Same adapter pattern as the rest:
the ``elevenlabs`` SDK is an optional dependency imported lazily, a client may be injected for
tests, and the convert call's streamed bytes are written to ``out_path``.

Requires ELEVENLABS_API_KEY. NOTE: not wired into the authoring loop yet (see ``creation.base``).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from videogen.creation.base import AudioKind

# A neutral, widely-available default voice ("Rachel"); override per call for a different read.
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
_TTS_MODEL = "eleven_multilingual_v2"


class ElevenLabsAudioCreator:
    """Creates speech, sound effects, or music from text prompts via the ElevenLabs SDK."""

    def __init__(
        self,
        *,
        default_voice_id: str = _DEFAULT_VOICE_ID,
        tts_model: str = _TTS_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._default_voice_id = default_voice_id
        self._tts_model = tts_model
        self._client = client if client is not None else _build_client(api_key)

    def create_audio(
        self,
        *,
        prompt: str,
        out_path: Path,
        kind: AudioKind = AudioKind.speech,
        voice_id: str | None = None,
    ) -> Path:
        if kind is AudioKind.speech:
            audio = self._client.text_to_speech.convert(
                voice_id=voice_id or self._default_voice_id,
                text=prompt,
                model_id=self._tts_model,
            )
        elif kind is AudioKind.sfx:
            audio = self._client.text_to_sound_effects.convert(text=prompt)
        else:  # music
            audio = self._client.music.compose(prompt=prompt)
        _write_stream(audio, out_path)
        return out_path


def _write_stream(audio: bytes | Iterable[bytes], out_path: Path) -> None:
    """Write the SDK's audio output -- bytes or a stream of byte chunks -- to disk."""
    with out_path.open("wb") as handle:
        if isinstance(audio, bytes | bytearray):
            handle.write(audio)
        else:
            for chunk in audio:
                handle.write(chunk)


def _build_client(api_key: str | None) -> Any:
    try:
        from elevenlabs.client import ElevenLabs
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "audio creation needs the elevenlabs SDK; install it with "
            "`uv sync --extra creation` and set ELEVENLABS_API_KEY"
        ) from exc
    key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    return ElevenLabs(api_key=key) if key else ElevenLabs()
