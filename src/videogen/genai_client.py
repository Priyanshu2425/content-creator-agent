"""Shared google-genai client factory with Application Default Credentials (ADC) support.

The google-genai SDK has two backends, and this is the one place the project chooses between them:

- **Vertex AI + ADC (recommended)** — no secret key. Set ``GOOGLE_GENAI_USE_VERTEXAI=true`` plus
  ``GOOGLE_CLOUD_PROJECT`` and ``GOOGLE_CLOUD_LOCATION``; credentials resolve from Application
  Default Credentials (``gcloud auth application-default login``, a service account, or the cloud
  environment's own identity). Nothing secret lives in the repo or env beyond the project id.
- **Gemini Developer API (API key)** — ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``. The legacy path,
  kept as a fallback so existing key-based runs keep working.

``build_genai_client`` selects ADC/Vertex when ``GOOGLE_GENAI_USE_VERTEXAI`` is set, otherwise falls
back to an API key. Every Gemini caller (review, vision, describe, authoring, image/video creation)
goes through here, so switching the whole pipeline to ADC is a single env-var change.
"""

from __future__ import annotations

import os
from typing import Any

_DEFAULT_LOCATION = "us-central1"
_TRUTHY = {"1", "true", "yes", "on"}


def use_vertex_adc() -> bool:
    """True when the project is configured to authenticate via Vertex AI + ADC (no API key)."""
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in _TRUTHY


def have_gemini_credentials() -> bool:
    """True when *some* Gemini auth is available -- ADC/Vertex, or an API key."""
    return use_vertex_adc() or bool(
        os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    )


def build_genai_client(
    api_key: str | None = None,
    *,
    install_hint: str = "install it with `uv sync --extra creation` (or `--extra review`)",
) -> Any:
    """Construct a ``google.genai.Client``, preferring ADC/Vertex when configured.

    Raises a friendly ``RuntimeError`` (carrying ``install_hint``) if the SDK is not installed."""
    try:
        import google.genai as genai
    except ModuleNotFoundError as exc:  # surface an actionable hint, not a bare import error
        raise RuntimeError(f"this feature needs the google-genai SDK; {install_hint}") from exc

    if use_vertex_adc():
        # ADC via Vertex AI: no API key. project/location from env; credentials from ADC.
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION") or _DEFAULT_LOCATION
        return genai.Client(vertexai=True, project=project, location=location)

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=key) if key else genai.Client()
