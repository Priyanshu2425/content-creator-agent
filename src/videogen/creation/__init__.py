"""Media creation providers: generate new assets (image / video / audio) from text prompts.

The seam (``base``) is split by media kind; concrete providers implement the kinds they can serve:
``GoogleMediaCreator`` (image via Imagen, video via Veo) and ``ElevenLabsAudioCreator`` (speech /
sfx / music). Imports are lazy (via ``__getattr__``) so importing this package pulls in no optional
SDK; an SDK loads only when a concrete provider is constructed.

NOTE: these are scaffolding -- not wired into the authoring loop yet (see ``base``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from videogen.creation.base import (
    AudioCreator,
    AudioKind,
    ImageCreator,
    VideoCreator,
)

if TYPE_CHECKING:
    from videogen.creation.elevenlabs import ElevenLabsAudioCreator
    from videogen.creation.google import GoogleMediaCreator

__all__ = [
    "AudioCreator",
    "AudioKind",
    "ElevenLabsAudioCreator",
    "GoogleMediaCreator",
    "ImageCreator",
    "VideoCreator",
]

_MODULES = {
    "GoogleMediaCreator": "google",
    "ElevenLabsAudioCreator": "elevenlabs",
}


def __getattr__(name: str) -> Any:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
