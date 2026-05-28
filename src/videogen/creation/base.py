"""Media creation seam: generate new assets when the brief lacks the footage it needs.

When no b-roll is supplied (or the agent wants a shot that does not exist), the authoring system
can *create* media -- an image or a video from a text prompt, or audio (voiceover / sound effect /
music). These Protocols are that seam. They are split by media kind so each can use the best
backend: image and video via a generative visual model (the Google adapter uses Imagen + Veo),
audio via ElevenLabs.

Each provider writes the created media to ``out_path`` and returns it, mirroring the render
backends' file-out contract -- so a created file slots straight into the asset library like any
ingested asset.

NOTE: these are NOT wired into the authoring loop yet. ``agent.tools.DRAFT_TOOLS`` describes the
intended tool surface; activation (advertising the tools, dispatching them, and persisting created
assets into the run folder) comes in a later step.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol


class AudioKind(StrEnum):
    """What an ``AudioCreator`` should synthesize: spoken voiceover, a sound effect, or music."""

    speech = "speech"
    sfx = "sfx"
    music = "music"


class ImageCreator(Protocol):
    """Generates a still image from a text prompt, written to ``out_path`` (PNG/JPEG)."""

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str = "9:16") -> Path: ...


class VideoCreator(Protocol):
    """Generates a video clip from a text prompt, written to ``out_path`` (mp4)."""

    def create_video(
        self,
        *,
        prompt: str,
        out_path: Path,
        aspect_ratio: str = "9:16",
        duration: float | None = None,
    ) -> Path: ...


class AudioCreator(Protocol):
    """Generates audio (speech / sfx / music) from a text prompt, written to ``out_path``."""

    def create_audio(
        self,
        *,
        prompt: str,
        out_path: Path,
        kind: AudioKind = AudioKind.speech,
        voice_id: str | None = None,
    ) -> Path: ...
