"""GeminiDescribeAgent: generates visual descriptions and usage advice for image b-roll assets.

Given a list of assets, a brief, and the transcript, it sends every image asset to Gemini in a
*single* structured call and asks, per asset, for two things:
  - ``description``: what the asset visually shows (1–2 sentences, factual).
  - ``usage_advice``: where it fits best in *this* video, referencing the transcript.

The agent is image-only: video and audio assets are skipped. Uploading video is reserved for the
review agent (which uploads the finished mp4), so the describer never touches the Files API —
every image is sent inline, labelled by asset id, and the model returns one array entry per asset.

The results come back as a ``dict[asset_id, AssetDescription]``. The caller (cli.Pipeline) merges
them into the ``AssetFact`` objects before the Manifest is built, so the authoring agent reads
both fields inline next to every asset in its perception packet. Assets the model omits simply
carry no description.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videogen import log, tracing
from videogen.agent.perception import AssetFact

_DEFAULT_MODEL = "gemini-2.5-flash-lite"

_SYSTEM = """\
You are a b-roll analysis assistant for a short-form video editor. You are shown one or more \
media assets (still images) that will be used as b-roll alongside a host recording. You are also \
given the video brief and the host's transcript.

Each image is preceded by a line of the form `Asset <id>:`. For every image, return one object \
with these keys:
- "asset_id": the exact id from the `Asset <id>:` label that precedes the image.
- "description": a factual visual description of what the asset shows (1–2 sentences, concrete \
and specific — describe the subject, setting, action, and mood).
- "usage_advice": a specific recommendation for where and how to use this asset in the video, \
referencing the actual words or moments from the transcript where it would land best \
(1–2 sentences).

Return one object per image, in the order the images were given.
"""

_SCHEMA: dict[str, Any] = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "asset_id": {"type": "STRING"},
            "description": {"type": "STRING"},
            "usage_advice": {"type": "STRING"},
        },
        "required": ["asset_id", "description", "usage_advice"],
    },
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


class GeminiDescribeAgent:
    """Describes every image asset in a manifest with a single Gemini vision call."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)

    def describe_all(
        self,
        assets: list[AssetFact],
        *,
        brief: str,
        transcript: str,
    ) -> dict[str, AssetDescription]:
        """Return a description + usage advice for each image asset, keyed by asset id.

        Only ``image`` assets are considered; video and audio are skipped. Every image is sent in
        one structured call. Images that fail to read are dropped from the batch; if the call
        itself fails the whole batch yields nothing (best-effort, the describer is optional).
        """
        import json

        contents: list[Any] = [
            f"Brief:\n{brief}\n\nTranscript:\n{transcript}\n\n"
            "Describe each of the following images and advise where it fits best in the video."
        ]
        included: list[str] = []
        for asset in assets:
            if asset.type != "image":
                continue
            part = self._image_part(asset)
            if part is None:
                continue
            contents.append(f"Asset {asset.id}:")
            contents.append(part)
            included.append(asset.id)

        if not included:
            log.get().describe_done(0)
            return {}

        try:
            with tracing.model_generation(
                "gemini-describe",
                system=_SYSTEM,
                user_message=f"{len(included)} image asset(s): {', '.join(included)}",
                model=self._model,
            ):
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config={
                        "system_instruction": _SYSTEM,
                        "response_mime_type": "application/json",
                        "response_schema": _SCHEMA,
                    },
                )
            rows = json.loads(response.text or "[]")
        except Exception as exc:
            log.get().describe_asset_warn("batch", str(exc))
            log.get().describe_done(0)
            return {}

        results: dict[str, AssetDescription] = {}
        for row in rows if isinstance(rows, list) else []:
            asset_id = str(row.get("asset_id", "")).strip()
            desc = str(row.get("description", "")).strip()
            if not asset_id or not desc:
                continue
            results[asset_id] = AssetDescription(
                description=desc,
                usage_advice=str(row.get("usage_advice", "")).strip(),
            )
            log.get().describe_asset_ok(asset_id)

        tracing.update_generation_output(f"{len(results)} described")
        log.get().describe_done(len(results))
        return results

    def _image_part(self, asset: AssetFact) -> Any:
        """Build the inline Gemini content part for an image asset, or None if it can't be read."""
        try:
            path = Path(asset.source)
            mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
            return {"inline_data": {"mime_type": mime, "data": path.read_bytes()}}
        except Exception as exc:
            log.get().describe_asset_warn(asset.id, str(exc))
            return None


def _build_client(api_key: str | None) -> Any:
    from videogen.genai_client import build_genai_client

    return build_genai_client(
        api_key,
        install_hint=(
            "the asset describer needs the google-genai SDK; install it with `uv sync --extra review`, then authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or an API key"
        ),
    )
