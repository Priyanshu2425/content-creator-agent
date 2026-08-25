"""NanoBananaCreator: still-image creation via Nano Banana (Gemini 2.5 Flash Image).

Implements the ``ImageCreator`` half of the creation seams — image only, no video. Follows the
same provider-adapter pattern as ``google.py`` and ``kling.py``: the google-genai SDK is an
optional dependency imported lazily (already pulled in by the review/creation extras), an SDK
client may be injected for tests, and the only job here is translating a prompt + output path
into the SDK's ``generate_content`` call and writing the returned image bytes back.

Nano Banana returns the image inline on a normal ``generate_content`` response: the request asks
for the IMAGE response modality and an ``image_config`` carrying the aspect ratio, and the bytes
come back in a part's ``inline_data``. Requires GEMINI_API_KEY or GOOGLE_API_KEY.
"""

from __future__ import annotations

import base64
import random
import time
from pathlib import Path
from typing import Any

from videogen import log, tracing

_IMAGE_MODEL = "gemini-2.5-flash-image"

# Parallel b-roll generation (ThreadPoolExecutor in GenerateBrollAgent) spikes Gemini's per-minute
# quota and the API answers 429 RESOURCE_EXHAUSTED. Those are transient, so retry with jittered
# exponential backoff before giving up on a slot. Tests set ``_RETRY_BASE_SECONDS = 0`` to skip the
# sleep, mirroring ``google._POLL_SECONDS``.
_MAX_ATTEMPTS = 5
_RETRY_BASE_SECONDS = 2.0


def _is_rate_limited(exc: Exception) -> bool:
    """Whether ``exc`` is a transient rate-limit / quota error worth retrying (429)."""
    if getattr(exc, "code", None) == 429 or getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).upper()
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _build_contents(prompt: str, reference_images: tuple[bytes, ...]) -> list[Any]:
    """Build the contents list for generate_content, prepending brand-kit reference images."""
    if not reference_images:
        return [prompt]
    parts: list[Any] = []
    for img_bytes in reference_images:
        mime = "image/jpeg" if img_bytes[:3] == b"\xff\xd8\xff" else "image/png"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(img_bytes).decode()}})
    parts.append({"text": f"Use the above image(s) as brand style reference. Generate: {prompt}"})
    return [{"role": "user", "parts": parts}]


class NanoBananaCreator:
    """Creates stills from text prompts via Nano Banana (Gemini 2.5 Flash Image)."""

    def __init__(
        self,
        *,
        model: str = _IMAGE_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
        reference_images: tuple[bytes, ...] = (),
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)
        self._reference_images = reference_images

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str = "9:16") -> Path:
        with tracing.media_create_span(
            "nano-banana-create-image",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            model=self._model,
        ):
            contents = _build_contents(prompt, self._reference_images)
            response = self._generate_with_retry(contents, aspect_ratio)
            out_path.write_bytes(_extract_image_bytes(response))
            tracing.update_media_create_output(str(out_path))
        return out_path

    def _generate_with_retry(self, contents: list[Any], aspect_ratio: str) -> Any:
        """Call ``generate_content``, retrying transient 429s with jittered exponential backoff.

        A non-rate-limit error is re-raised immediately; a 429 is retried up to ``_MAX_ATTEMPTS``
        times, after which the last error propagates so the caller (per-slot in GenerateBrollAgent)
        still records the failure rather than hanging.
        """
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config={
                        "response_modalities": ["IMAGE"],
                        "image_config": {"aspect_ratio": aspect_ratio},
                    },
                )
            except Exception as exc:
                if not _is_rate_limited(exc) or attempt == _MAX_ATTEMPTS - 1:
                    raise
                backoff = _RETRY_BASE_SECONDS * (2**attempt)
                wait = backoff + random.uniform(0.0, backoff)  # jitter de-syncs parallel retries
                log.get().media_retry(
                    what=f"nano-banana ({self._model})",
                    attempt=attempt + 1,
                    max_attempts=_MAX_ATTEMPTS,
                    backoff_s=wait,
                    error=str(exc),
                )
                time.sleep(wait)
        raise RuntimeError("unreachable: retry loop exited without returning or raising")


def _extract_image_bytes(response: Any) -> bytes:
    """Pull the first inline image payload out of a Nano Banana generate_content response."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None)
            if data:
                return data  # type: ignore[no-any-return]
    raise RuntimeError("Nano Banana returned no image data in the response")


def _build_client(api_key: str | None) -> Any:
    from videogen.genai_client import build_genai_client

    return build_genai_client(
        api_key,
        install_hint=(
            "b-roll image generation needs the google-genai SDK; install it with `uv sync --extra creation`, then authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or an API key"
        ),
    )
