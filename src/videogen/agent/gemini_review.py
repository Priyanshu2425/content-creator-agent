"""GeminiReviewAgent: the real video-capable ReviewAgent over google-genai (Phase 9, ADR 0004).

Phase 8b reserved full-motion review for a separate, video-capable model behind the ``ReviewAgent``
seam and deferred the concrete adapter; this is it. It uploads the finished mp4, asks a video model
to watch it in full and return structured, timestamped notes (the ``REVIEW_SYSTEM_PROMPT`` contract
and the four categories), and parses that JSON into the neutral ``ReviewFeedback`` the finalization
gate consumes. The gate depends only on the ``ReviewAgent`` interface, so this stays swappable.

The ``google-genai`` SDK is an optional dependency, imported lazily: the package and its
deterministic tests load without it, and the install hint surfaces only on a real run. A client may
be injected (the test seam). Uploaded video must reach the ACTIVE state before it can be referenced,
so the adapter waits for it rather than racing the upload.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from videogen.agent.prompts import REVIEW_SYSTEM_PROMPT
from videogen.agent.review import (
    FeedbackItem,
    ReviewCategory,
    ReviewFeedback,
    Severity,
)
from videogen.kernel.composition import Composition

# A fast, video-capable default; override per run for a stronger reviewer. The gate is indifferent.
_DEFAULT_MODEL = "gemini-2.5-flash"

# The structured-output contract handed to the model so its reply parses into ReviewFeedback.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "no_actionable_issues": {"type": "BOOLEAN"},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "at": {"type": "NUMBER"},
                    "until": {"type": "NUMBER"},
                    "category": {
                        "type": "STRING",
                        "enum": [c.value for c in ReviewCategory],
                    },
                    "severity": {"type": "STRING", "enum": [s.value for s in Severity]},
                    "note": {"type": "STRING"},
                },
                "required": ["at", "category", "severity", "note"],
            },
        },
    },
    "required": ["no_actionable_issues", "items"],
}


def _parse_feedback(data: dict[str, Any]) -> ReviewFeedback:
    """Turn the model's structured JSON into the neutral ReviewFeedback the gate consumes."""
    items = tuple(
        FeedbackItem(
            at=float(item["at"]),
            until=None if item.get("until") is None else float(item["until"]),
            category=ReviewCategory(item["category"]),
            severity=Severity(item["severity"]),
            note=str(item["note"]),
        )
        for item in data.get("items", [])
    )
    no_issues = bool(data.get("no_actionable_issues", not items))
    return ReviewFeedback(items=items, no_actionable_issues=no_issues)


def _prompt(composition: Composition, timeline: str) -> str:
    """The per-review user prompt: the document and timeline as context for the attached video."""
    return (
        "Review the attached rendered video against this Composition.\n\n"
        f"## Composition\n{composition.model_dump_json(by_alias=True)}\n\n"
        f"## Timeline (resolver, seconds)\n{timeline}\n\n"
        "Watch the video in full and return your structured feedback."
    )


def _is_active(file: Any) -> bool:
    state = getattr(file, "state", None)
    if state is None:
        return True
    name = getattr(state, "name", None) or str(state)
    return "ACTIVE" in str(name)


class GeminiReviewAgent:
    """A ``ReviewAgent`` that watches the finished mp4 with a real video model and reports notes."""

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

    def review(self, *, video: Path, composition: Composition, timeline: str) -> ReviewFeedback:
        uploaded = self._client.files.upload(file=str(video))
        uploaded = self._await_active(uploaded)
        response = self._client.models.generate_content(
            model=self._model,
            contents=[uploaded, _prompt(composition, timeline)],
            config={
                "system_instruction": REVIEW_SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": _RESPONSE_SCHEMA,
            },
        )
        return _parse_feedback(json.loads(response.text))

    def _await_active(self, file: Any) -> Any:
        """Wait for an uploaded video to finish processing before it is referenced in a request."""
        deadline = time.monotonic() + self._upload_timeout
        while not _is_active(file):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"uploaded video {file.name} was not ACTIVE in time")
            time.sleep(self._poll_interval)
            file = self._client.files.get(name=file.name)
        return file


def _build_client(api_key: str | None) -> Any:
    try:
        import google.genai as genai
    except ModuleNotFoundError as exc:  # optional dependency
        raise RuntimeError(
            "the review model needs the google-genai SDK; install it with "
            "`uv sync --extra review` and set GOOGLE_API_KEY (or GEMINI_API_KEY)"
        ) from exc
    return genai.Client(api_key=api_key) if api_key else genai.Client()
