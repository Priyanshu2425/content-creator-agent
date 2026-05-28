"""GoogleMediaCreator: image creation via Imagen and video creation via Veo (google-genai SDK).

Implements the ``ImageCreator`` and ``VideoCreator`` seams. Same provider-adapter pattern as the
authoring model clients: the google-genai SDK is an optional dependency imported lazily (it is
already pulled in by the review extra), an SDK client may be injected for tests, and the only job
here is translating a prompt + output path into the SDK's generate call and writing the bytes back.

Veo is long-running: ``generate_videos`` returns an operation that is polled to completion before
the rendered clip's bytes are available. Requires GEMINI_API_KEY or GOOGLE_API_KEY.

NOTE: not wired into the authoring loop yet (see ``creation.base``). Model ids are sensible
defaults; override per call site as Google's generally-available model names move.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

_IMAGE_MODEL = "imagen-4.0-generate-001"
_VIDEO_MODEL = "veo-3.0-generate-preview"
_POLL_SECONDS = 10.0


class GoogleMediaCreator:
    """Creates stills (Imagen) and clips (Veo) from text prompts via the google-genai SDK."""

    def __init__(
        self,
        *,
        image_model: str = _IMAGE_MODEL,
        video_model: str = _VIDEO_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._image_model = image_model
        self._video_model = video_model
        self._client = client if client is not None else _build_client(api_key)

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str = "9:16") -> Path:
        response = self._client.models.generate_images(
            model=self._image_model,
            prompt=prompt,
            config={"number_of_images": 1, "aspect_ratio": aspect_ratio},
        )
        image = response.generated_images[0].image
        out_path.write_bytes(image.image_bytes)
        return out_path

    def create_video(
        self,
        *,
        prompt: str,
        out_path: Path,
        aspect_ratio: str = "9:16",
        duration: float | None = None,
    ) -> Path:
        config: dict[str, Any] = {"aspect_ratio": aspect_ratio}
        if duration is not None:
            config["duration_seconds"] = int(round(duration))
        operation = self._client.models.generate_videos(
            model=self._video_model, prompt=prompt, config=config
        )
        while not operation.done:
            time.sleep(_POLL_SECONDS)
            operation = self._client.operations.get(operation)
        video = operation.response.generated_videos[0].video
        self._client.files.download(file=video)
        out_path.write_bytes(video.video_bytes)
        return out_path


def _build_client(api_key: str | None) -> Any:
    try:
        import google.genai as genai
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "media creation needs the google-genai SDK; install it with "
            "`uv sync --extra creation` and set GEMINI_API_KEY (or GOOGLE_API_KEY)"
        ) from exc
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=key) if key else genai.Client()
