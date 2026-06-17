"""GeminiVisionAdvisor: the real ``VisionAdvisor`` over google-genai (ADR 0007).

The blind authoring client's ``consult_placement`` tool renders a still and asks for text advice;
this answers it with a vision-capable Gemini model. It mirrors ``gemini_review.py`` (lazy SDK
import, injectable ``client=`` test seam, ``gemini-2.5-flash`` default) but differs in two ways
that matter: the image is sent **inline** (a still is small, so no ``files.upload``/ACTIVE-poll
dance like the video reviewer), and the reply is **free text**, not structured JSON.

The neutral ``VisionAdvisor`` Protocol lives in ``vision_advice``; this concrete adapter is imported
only where the pipeline is wired, so the loop and services never import a provider SDK.
"""

from __future__ import annotations

from typing import Any

from videogen import tracing
from videogen.agent.prompts import ADVICE_SYSTEM_PROMPT

# A fast, vision-capable default; override per run for a stronger advisor. The loop is indifferent.
_DEFAULT_MODEL = "gemini-2.5-flash"


def _advice_prompt(question: str, context: str) -> str:
    """The per-call user prompt: the agent's question plus the loop-supplied timeline context."""
    return (
        "You are shown the current rendered frame. Answer this question about it with concrete, "
        f"actionable advice in plain prose:\n\n{question}\n\n"
        f"## Context (where this frame sits)\n{context}"
    )


class GeminiVisionAdvisor:
    """A ``VisionAdvisor`` that answers placement questions about a still via Gemini."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)

    def advise(self, *, image: bytes, question: str, context: str) -> str:
        # Inline image part (PartDict shape) -- avoids importing the SDK types here, so the
        # deterministic tests run against a fake client with no google-genai installed.
        image_part = {"inline_data": {"mime_type": "image/png", "data": image}}
        with tracing.model_generation(
            "gemini-vision-advise",
            system=ADVICE_SYSTEM_PROMPT,
            user_message=question[:300],
            model=self._model,
        ):
            response = self._client.models.generate_content(
                model=self._model,
                contents=[image_part, _advice_prompt(question, context)],
                config={"system_instruction": ADVICE_SYSTEM_PROMPT},
            )
        advice = response.text or ""
        tracing.update_generation_output(advice[:500])
        return advice


def _build_client(api_key: str | None) -> Any:
    from videogen.genai_client import build_genai_client

    return build_genai_client(
        api_key,
        install_hint=(
            "the vision advisor needs the google-genai SDK; install it with `uv sync --extra review`, then authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or an API key"
        ),
    )
