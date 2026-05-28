"""GeminiDescribeAgent: generates visual descriptions and usage advice for every b-roll asset.

Given a list of assets, a brief, and the transcript, it uploads each non-audio asset to Gemini
and asks two questions in one structured call:
  - ``description``: what the asset visually shows (1–2 sentences, factual).
  - ``usage_advice``: where it fits best in *this* video, referencing the transcript.

Videos are uploaded via the Gemini Files API (same ACTIVE-poll pattern as GeminiReviewAgent);
images are sent inline (same as GeminiVisionAdvisor). Audio assets are silently skipped.

The results come back as a ``dict[asset_id, AssetDescription]``. The caller (cli.Pipeline) merges
them into the ``AssetFact`` objects before the Manifest is built, so the authoring agent reads
both fields inline next to every asset in its perception packet.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videogen import log
from videogen.agent.perception import AssetFact

_DEFAULT_MODEL = "gemini-2.5-flash"

_SYSTEM = """\
You are a b-roll analysis assistant for a short-form video editor. You are shown a media asset \
(image or video clip) that will be used as b-roll alongside a host recording. You are also given \
the video brief and the host's transcript.

Return a JSON object with exactly two keys:
- "description": a factual visual description of what the asset shows (1–2 sentences, concrete \
and specific — describe the subject, setting, action, and mood).
- "usage_advice": a specific recommendation for where and how to use this asset in the video, \
referencing the actual words or moments from the transcript where it would land best (1–2 sentences).
"""

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "description": {"type": "STRING"},
        "usage_advice": {"type": "STRING"},
    },
    "required": ["description", "usage_advice"],
}

_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@dataclass(frozen=True)
class AssetDescription:
    description: str
    usage_advice: str


class _RateLimiter:
    """Sliding-window rate limiter: at most ``limit`` calls within any ``window``-second span.

    ``acquire()`` blocks until a slot is free and returns how long it waited (seconds), so the
    caller can log it. Timestamps are recorded *after* the wait so back-to-back calls accumulate
    correctly.
    """

    def __init__(self, limit: int = 5, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._timestamps: deque[float] = deque()

    def acquire(self) -> float:
        now = time.monotonic()
        # Drop timestamps that have fallen outside the window.
        while self._timestamps and now - self._timestamps[0] >= self._window:
            self._timestamps.popleft()

        waited = 0.0
        if len(self._timestamps) >= self._limit:
            # Wait until the oldest slot expires and opens a new one.
            wait_until = self._timestamps[0] + self._window
            wait = wait_until - time.monotonic()
            if wait > 0:
                waited = wait
                time.sleep(wait)
            # Drop timestamps that are now outside the window after the sleep.
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] >= self._window:
                self._timestamps.popleft()

        self._timestamps.append(time.monotonic())
        return waited


class GeminiDescribeAgent:
    """Describes every non-audio asset in a manifest using Gemini vision."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
        upload_timeout: float = 120.0,
        poll_interval: float = 1.0,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)
        self._upload_timeout = upload_timeout
        self._poll_interval = poll_interval
        self._rate_limiter = _RateLimiter(limit=5, window=60.0)

    def describe_all(
        self,
        assets: list[AssetFact],
        *,
        brief: str,
        transcript: str,
    ) -> dict[str, AssetDescription]:
        """Return a description + usage advice for each asset, keyed by asset id.

        Assets whose type is ``audio`` are skipped (nothing visual to describe). Individual
        failures are logged and skipped; the caller continues with whatever succeeds.
        """
        results: dict[str, AssetDescription] = {}
        for asset in assets:
            if asset.type == "audio":
                continue
            try:
                desc = self._describe_one(asset, brief=brief, transcript=transcript)
                if desc is not None:
                    results[asset.id] = desc
                    log.get().describe_asset_ok(asset.id)
            except Exception as exc:
                log.get().describe_asset_warn(asset.id, str(exc))
        log.get().describe_done(len(results))
        return results

    def _describe_one(
        self, asset: AssetFact, *, brief: str, transcript: str
    ) -> AssetDescription | None:
        import json

        media_part = self._media_part(asset)
        if media_part is None:
            return None

        prompt = (
            f"Brief:\n{brief}\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Describe this asset and advise where it fits best in the video."
        )
        waited = self._rate_limiter.acquire()
        if waited > 0:
            log.get().describe_rate_wait(waited)
        response = self._client.models.generate_content(
            model=self._model,
            contents=[media_part, prompt],
            config={
                "system_instruction": _SYSTEM,
                "response_mime_type": "application/json",
                "response_schema": _SCHEMA,
            },
        )
        data = json.loads(response.text or "{}")
        desc = str(data.get("description", "")).strip()
        advice = str(data.get("usage_advice", "")).strip()
        if not desc:
            return None
        return AssetDescription(description=desc, usage_advice=advice)

    def _media_part(self, asset: AssetFact) -> Any:
        """Build the Gemini content part for this asset: inline for images, Files API for videos."""
        path = Path(asset.source)
        if asset.type == "image":
            mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
            return {"inline_data": {"mime_type": mime, "data": path.read_bytes()}}
        # video: upload via Files API and wait for ACTIVE
        uploaded = self._client.files.upload(file=str(path))
        return self._await_active(uploaded)

    def _await_active(self, file: Any) -> Any:
        deadline = time.monotonic() + self._upload_timeout
        while not _is_active(file):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"uploaded asset {file.name} was not ACTIVE in time")
            time.sleep(self._poll_interval)
            file = self._client.files.get(name=file.name)
        return file


def _is_active(file: Any) -> bool:
    state = getattr(file, "state", None)
    if state is None:
        return True
    name = getattr(state, "name", None) or str(state)
    return "ACTIVE" in str(name)


def _build_client(api_key: str | None) -> Any:
    try:
        import google.genai as genai
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the asset describer needs the google-genai SDK; install it with "
            "`uv sync --extra review` and set GOOGLE_API_KEY (or GEMINI_API_KEY)"
        ) from exc
    return genai.Client(api_key=api_key) if api_key else genai.Client()
