"""PerplexityBrollAgent: fetches relevant b-roll images/videos via Perplexity web search.

Two-turn exchange with sonar-pro:
  1. Extract concrete visual search queries from the brief + transcript AND classify content
     into one or more buckets (stock / news / science). The bucket drives which curated
     source list is injected into Turn 2 — keeping the prompt tight and results more accurate.
  2. Search the web using only the 4-5 most relevant sources for the detected bucket(s) and
     return up to _CANDIDATE_POOL direct-download URLs.

Each URL is then tried in order; the downloader stops as soon as ``limit`` downloads succeed
(so broken/paywalled links are skipped without burning the quota).
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
# Always fetch a large candidate pool so broken links can be skipped without running short.
_CANDIDATE_POOL = 100
# How many sources to inject per detected category bucket.
_SOURCES_PER_BUCKET = 4

# Curated, reliable sources bucketed by content type.
# Within each list, earlier entries are higher quality / more likely to yield direct downloads.
SOURCE_BUCKETS: dict[str, list[str]] = {
    "stock": [
        "pexels.com",
        "pixabay.com",
        "unsplash.com",
        "coverr.io",
        "mixkit.co",
        "videvo.net",
        "lifeofpix.com",
        "stocksnap.io",
        "reshot.com",
        "freestocktextures.com",
    ],
    "news": [
        "commons.wikimedia.org",
        "loc.gov",
        "archive.org",
        "flickr.com/commons",
        "apnews.com",
        "reuters.com/pictures",
        "europeana.eu",
        "dvidshub.net",
        "un.org/photos",
        "gettyimages.com",
    ],
    "science": [
        "nasa.gov",
        "noaa.gov",
        "nih.gov",
        "usgs.gov",
        "cdc.gov",
        "science.nasa.gov",
        "esa.int",
        "pond5.com/free",
        "ncbi.nlm.nih.gov",
    ],
}

_VALID_CATEGORIES = frozenset(SOURCE_BUCKETS)

_TURN1_SYSTEM = """\
You are a b-roll research assistant for short-form video production. Given a video brief and \
transcript, do two things and return a single JSON object with two keys:
- "queries": an array of specific visual search query strings — each must describe a concrete \
visual scene, object, or action (not an abstract concept).
- "categories": an array containing one or more of exactly these strings: "stock", "news", \
"science". Choose based on the content: "stock" for lifestyle, nature, business, or general \
footage; "news" for current events, photojournalism, or historical archives; "science" for \
technical, medical, space, environmental, or data-driven topics. Include all that apply.
No prose, only valid JSON.\
"""

# Turn 2 system prompt template — {sources} is filled with the selected source list at runtime.
_TURN2_SYSTEM_TMPL = """\
You are a b-roll researcher with live web search capability. Search these sources to find \
specific media assets: {sources}.

CRITICAL: Return URLs of INDIVIDUAL ASSETS — not search pages, not query URLs.

BAD (search/query pages — do NOT return these):
  pexels.com/search/videos/film+director
  unsplash.com/s/photos/movie-set
  pixabay.com/videos/search/director

GOOD (individual asset pages or direct file URLs — return these):
  pexels.com/video/movie-director-on-set-12345678/
  images.unsplash.com/photo-1234567890abcdef.jpg
  cdn.pixabay.com/video/2023/01/01/12345-abc.mp4
  images.pexels.com/photos/12345678/pexels-photo-12345678.jpeg

Use your web search to find real, specific assets. Return a JSON object with a single key \
"links" containing an array of objects, each with: "url" (the individual asset page or direct \
file URL), "type" (either "image" or "video"), "description" (one sentence about what it shows). \
Return only real URLs you actually found — no constructed or placeholder URLs.\
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

        queries, categories = self._extract_queries(brief, transcript, limit)
        if not queries:
            log.get().broll_fetch_warn("no queries extracted from brief + transcript")
            return []

        sources = _select_sources(categories)
        links = self._fetch_links(queries, sources, _CANDIDATE_POOL, brief=brief, transcript=transcript)
        if not links:
            log.get().broll_fetch_warn("Perplexity returned no links")
            return []

        # Try candidates in order; stop as soon as ``limit`` downloads succeed.
        paths: list[Path] = []
        for idx, link in enumerate(links):
            if len(paths) >= limit:
                break
            out = _download(link, dest, idx)
            if out is not None:
                log.get().broll_fetch_ok(link.url, str(out))
                paths.append(out)
            else:
                log.get().broll_fetch_warn(f"download failed: {link.url}")

        log.get().broll_fetch_done(len(paths))
        return paths

    def _extract_queries(
        self, brief: str, transcript: str, limit: int
    ) -> tuple[list[str], list[str]]:
        """Turn 1: derive search queries AND content category buckets from the brief + transcript."""
        user = (
            f"Brief:\n{brief}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Extract up to {limit} visual search queries and classify the content category."
        )
        raw = self._complete(_TURN1_SYSTEM, user)
        try:
            data = json.loads(raw)
            queries = [str(q) for q in data.get("queries", []) if q]
            categories = [c for c in data.get("categories", []) if c in _VALID_CATEGORIES]
            if not categories:
                categories = ["stock"]  # safe default for unclassified content
            return queries, categories
        except (json.JSONDecodeError, AttributeError):
            log.get().broll_fetch_warn(f"turn-1 parse error (first 200 chars): {raw[:200]}")
            return [], ["stock"]

    def _fetch_links(
        self, queries: list[str], sources: list[str], pool: int, *, brief: str, transcript: str
    ) -> list[_BrollLink]:
        """Turn 2: search the web for URLs, restricting to the bucket-selected sources."""
        source_hint = ", ".join(sources)
        system = _TURN2_SYSTEM_TMPL.format(sources=source_hint)
        user = (
            f"Brief:\n{brief}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Search for b-roll footage matching these queries:\n"
            f"{json.dumps(queries, indent=2)}\n\n"
            f"Return up to {pool} items total."
        )
        raw = self._complete(system, user)
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


def _select_sources(categories: list[str]) -> list[str]:
    """Pick the top ``_SOURCES_PER_BUCKET`` sources from each detected category, deduplicated."""
    seen: set[str] = set()
    selected: list[str] = []
    for cat in categories:
        for src in SOURCE_BUCKETS.get(cat, [])[:_SOURCES_PER_BUCKET]:
            if src not in seen:
                seen.add(src)
                selected.append(src)
    return selected


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
