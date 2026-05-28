"""PerplexityBrollAgent: fetches relevant b-roll images/videos via Perplexity web search.

Two-turn exchange with sonar-pro:
  1. Extract concrete visual search queries from the brief + transcript.
  2. Search the web for those queries and return direct-download URLs.

Each URL is then downloaded: plain HTTP GET first, yt-dlp fallback for streaming pages.
Individual failures are logged and skipped; the pipeline continues with whatever succeeds.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from videogen import log

_BASE_URL = "https://api.perplexity.ai"
_DEFAULT_MODEL = "sonar-pro"

_TURN1_SYSTEM = """\
You are a b-roll research assistant for short-form video production. Given a video brief and \
transcript, extract specific visual search queries for relevant b-roll footage (images and video \
clips). Return a JSON object with a single key "queries" containing an array of strings. \
Each query must describe a concrete visual scene, object, or action. No prose, only valid JSON.\
"""

_TURN2_SYSTEM = """\
You are a b-roll researcher with live web search capability. For each query, find a direct-download \
URL for a relevant image or video clip from your search results. Return a JSON object with a \
single key "links" containing an array of objects, each with: "url" (a direct URL — preferably \
ending in .jpg/.jpeg/.png/.webp/.mp4/.mov/.webm — or a streamable video page URL if no direct \
link exists), "type" (either "image" or "video"), "description" (one sentence about what the \
asset shows). Return only real URLs you found via search — no placeholders or made-up links.\
"""


class _BrollLink(BaseModel):
    url: str
    type: str  # "image" or "video"
    description: str


class PerplexityBrollAgent:
    """Fetches b-roll assets via Perplexity web search and downloads them into the run folder."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)

    def fetch(
        self,
        brief: str,
        transcript: str,
        *,
        limit: int,
        dest: Path,
    ) -> list[Path]:
        """Return paths of successfully downloaded b-roll files, up to ``limit``."""
        dest.mkdir(parents=True, exist_ok=True)

        queries = self._extract_queries(brief, transcript, limit)
        if not queries:
            log.get().broll_fetch_warn("no queries extracted from brief + transcript")
            return []

        links = self._fetch_links(queries, limit)
        if not links:
            log.get().broll_fetch_warn("Perplexity returned no links")
            return []

        paths: list[Path] = []
        for idx, link in enumerate(links[:limit]):
            out = _download(link, dest, idx)
            if out is not None:
                log.get().broll_fetch_ok(link.url, str(out))
                paths.append(out)
            else:
                log.get().broll_fetch_warn(f"download failed: {link.url}")

        log.get().broll_fetch_done(len(paths))
        return paths

    def _extract_queries(self, brief: str, transcript: str, limit: int) -> list[str]:
        """Turn 1: derive search queries from the brief and transcript."""
        user = (
            f"Brief:\n{brief}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Extract up to {limit} visual search queries for b-roll footage."
        )
        raw = self._complete(_TURN1_SYSTEM, user)
        try:
            data = json.loads(raw)
            return [str(q) for q in data.get("queries", []) if q]
        except (json.JSONDecodeError, AttributeError):
            log.get().broll_fetch_warn(f"turn-1 parse error (first 200 chars): {raw[:200]}")
            return []

    def _fetch_links(self, queries: list[str], limit: int) -> list[_BrollLink]:
        """Turn 2: search the web for URLs matching the extracted queries."""
        user = (
            f"Search for b-roll footage matching these queries:\n"
            f"{json.dumps(queries, indent=2)}\n\n"
            f"Return up to {limit} items total."
        )
        raw = self._complete(_TURN2_SYSTEM, user)
        try:
            data = json.loads(raw)
            links: list[_BrollLink] = []
            for item in data.get("links", []):
                try:
                    links.append(_BrollLink.model_validate(item))
                except Exception:
                    pass
            return links
        except (json.JSONDecodeError, AttributeError):
            log.get().broll_fetch_warn(f"turn-2 parse error (first 200 chars): {raw[:200]}")
            return []

    def _complete(self, system: str, user: str) -> str:
        # Perplexity sonar models do not support {"type": "json_object"}; rely on the system
        # prompt's JSON instruction and extract the object from free-text if needed.
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return _extract_json(response.choices[0].message.content or "")


def _extract_json(text: str) -> str:
    """Return the first JSON object found in ``text``, or the raw text if none is found.

    Perplexity may wrap the JSON in prose or a markdown code fence; this strips that wrapper
    so the callers can always call ``json.loads`` on the result.
    """
    import re

    # Strip ```json ... ``` or ``` ... ``` code fences.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # Fall back: find the outermost {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _download(link: _BrollLink, dest: Path, idx: int) -> Path | None:
    """Try a plain HTTP GET first; fall back to yt-dlp for streaming/embed pages."""
    ext = _ext_from_url(link.url) or (".mp4" if link.type == "video" else ".jpg")
    out = dest / f"broll_{idx:02d}{ext}"

    # --- direct HTTP ---
    try:
        import urllib.request

        req = urllib.request.Request(link.url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            ct = resp.headers.get("Content-Type", "")
            if _is_media_ct(ct, link.url):
                out.write_bytes(resp.read())
                return out
    except Exception:
        pass

    # --- yt-dlp fallback ---
    try:
        template = str(dest / f"broll_{idx:02d}.%(ext)s")
        result = subprocess.run(
            ["yt-dlp", "-o", template, "--no-playlist", "--quiet", link.url],
            capture_output=True,
            timeout=90,
        )
        if result.returncode == 0:
            candidates = sorted(dest.glob(f"broll_{idx:02d}.*"))
            if candidates:
                return candidates[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _ext_from_url(url: str) -> str:
    known = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".mp4", ".mov", ".webm", ".mkv"}
    path = url.split("?")[0].lower()
    for ext in known:
        if path.endswith(ext):
            return ext
    return ""


def _is_media_ct(ct: str, url: str = "") -> bool:
    ct = ct.lower()
    if any(ct.startswith(p) for p in ("image/", "video/")):
        return True
    # Accept application/octet-stream only when the URL carries a known media extension.
    return ct.startswith("application/octet-stream") and bool(_ext_from_url(url))


def _build_client(api_key: str | None) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the b-roll fetch agent needs the openai SDK; "
            "install it with `uv sync --extra openai` and set PERPLEXITY_API_KEY"
        ) from exc
    key = api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise RuntimeError("PERPLEXITY_API_KEY is not set; export it or pass api_key= explicitly")
    return OpenAI(base_url=_BASE_URL, api_key=key)
