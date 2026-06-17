"""KlingMediaCreator: image and video creation via the Kling AI API.

Implements the ImageCreator and VideoCreator seams from creation.base. Follows the same
provider-adapter pattern as google.py: credentials come from env vars, HTTP is stdlib-only
(no extra SDK dependency), and the only job here is translating a prompt + output path into
API calls.

Auth: Kling uses JWT Bearer tokens derived from an AK/SK pair (KLING_ACCESS_KEY +
KLING_SECRET_KEY). Tokens expire in 30 minutes; a fresh one is minted per request.

Both image and video generation are async: submit → receive task_id → poll until
task_status == "succeeded" → download the result URL.

NOTE: not wired into the authoring loop yet (see creation.base).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from videogen import log, tracing

_BASE_URL = "https://api-singapore.klingai.com"
_IMAGE_MODEL = "kling-v3"
_VIDEO_MODEL = "kling-v3"
_POLL_SECONDS = 5.0
_TOKEN_TTL = 1800  # 30-minute expiry per Kling spec
_VIDEO_MIN_DURATION = 3
_VIDEO_MAX_DURATION = 15
_VIDEO_DEFAULT_DURATION = 5


def _make_jwt(access_key: str, secret_key: str) -> str:
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64(
        json.dumps({"iss": access_key, "exp": now + _TOKEN_TTL, "nbf": now - 5}).encode()
    )
    sig = _b64(
        hmac.new(
            secret_key.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
    )
    return f"{header}.{payload}.{sig}"


class KlingMediaCreator:
    """Creates stills (kling-v3) and clips (kling-v3) from text prompts."""

    def __init__(
        self,
        *,
        image_model: str = _IMAGE_MODEL,
        video_model: str = _VIDEO_MODEL,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._image_model = image_model
        self._video_model = video_model
        self._access_key = access_key or os.environ.get("KLING_ACCESS_KEY", "")
        self._secret_key = secret_key or os.environ.get("KLING_SECRET_KEY", "")
        if not self._access_key or not self._secret_key:
            raise RuntimeError(
                "Kling credentials missing; set KLING_ACCESS_KEY and KLING_SECRET_KEY"
            )

    # ------------------------------------------------------------------
    # Protocol: ImageCreator
    # ------------------------------------------------------------------

    def create_image(self, *, prompt: str, out_path: Path, aspect_ratio: str = "9:16") -> Path:
        with tracing.kling_span("kling-create-image", prompt=prompt, aspect_ratio=aspect_ratio):
            resp = self._post(
                "/v1/images/generations",
                {"model": self._image_model, "prompt": prompt, "aspect_ratio": aspect_ratio, "n": 1},
            )
            task_id: str = resp["data"]["task_id"]
            log.get().kling_submitted("image", task_id)
            url = self._poll_task(
                f"/v1/images/generations?task_id={task_id}",
                result_key="images",
                kind="image",
                task_id=task_id,
            )
            _download(url, out_path)
            tracing.update_kling_output(str(out_path))
        return out_path

    # ------------------------------------------------------------------
    # Protocol: VideoCreator
    # ------------------------------------------------------------------

    def create_video(
        self,
        *,
        prompt: str,
        out_path: Path,
        aspect_ratio: str = "9:16",
        duration: float | None = None,
    ) -> Path:
        dur = int(
            round(
                max(
                    _VIDEO_MIN_DURATION,
                    min(_VIDEO_MAX_DURATION, duration if duration is not None else _VIDEO_DEFAULT_DURATION),
                )
            )
        )
        with tracing.kling_span(
            "kling-create-video", prompt=prompt, aspect_ratio=aspect_ratio, duration=float(dur)
        ):
            resp = self._post(
                "/v1/videos/text2video",
                {
                    "model_name": self._video_model,
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": dur,
                },
            )
            task_id = resp["data"]["task_id"]
            log.get().kling_submitted("video", task_id)
            url = self._poll_task(
                f"/v1/videos/text2video/{task_id}",
                result_key="videos",
                kind="video",
                task_id=task_id,
            )
            _download(url, out_path)
            tracing.update_kling_output(str(out_path))
        return out_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _token(self) -> str:
        return _make_jwt(self._access_key, self._secret_key)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{_BASE_URL}{path}",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._send(req)

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> dict[str, Any]:
        """Send a request and raise a clear error for any Kling service-code failure."""
        import urllib.error

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                data = json.loads(raw)
            except Exception:
                raise RuntimeError(
                    f"Kling HTTP {exc.code} — {raw.decode(errors='replace')}"
                ) from exc
            _raise_for_service_code(exc.code, data)

        _raise_for_service_code(200, data)
        return data  # type: ignore[no-any-return]

    def _poll_task(
        self, poll_path: str, *, result_key: str, kind: str = "", task_id: str = ""
    ) -> str:
        """Poll a Kling task until succeeded; return the first asset's URL."""
        t0 = time.monotonic()
        attempt = 0
        while True:
            data = self._get(poll_path).get("data", {})
            # Image list endpoint wraps results in a list; video detail endpoint is a single object.
            task = data if isinstance(data, dict) and "task_status" in data else _first(data)
            status = task.get("task_status", "")
            elapsed_s = int(time.monotonic() - t0)
            log.get().kling_poll(kind, task_id, status, elapsed_s, attempt)
            if status in ("succeed", "succeeded"):
                assets = task["task_result"][result_key]
                url = assets[0]["url"]
                log.get()._event("kling_complete", kind=kind, task_id=task_id, elapsed_s=elapsed_s)
                return url  # type: ignore[no-any-return]
            if status in ("failed", "fail"):
                raise RuntimeError(
                    f"Kling task failed (path={poll_path}): "
                    f"{task.get('task_status_msg', 'no detail')}"
                )
            attempt += 1
            time.sleep(_POLL_SECONDS)


_SERVICE_CODE_MESSAGES: dict[int, str] = {
    1000: "authentication failed — check KLING_ACCESS_KEY / KLING_SECRET_KEY",
    1001: "Authorization header is empty",
    1002: "Authorization token is invalid",
    1003: "Authorization token is not yet valid (nbf in the future)",
    1004: "Authorization token has expired — token TTL is 30 min",
    1100: "account exception — verify account configuration",
    1101: "account in arrears (postpaid) — recharge the account",
    1102: "resource pack depleted or expired (prepaid) — purchase more or enable postpaid",
    1103: "unauthorized access to this API/model — check account permissions",
    1200: "invalid request parameters",
    1201: "invalid parameter value — see 'message' field for details",
    1202: "invalid HTTP method for this endpoint",
    1203: "requested resource does not exist (wrong model name?)",
    1300: "platform policy triggered",
    1301: "content security policy triggered — modify the prompt and retry",
    1302: "rate limit exceeded — reduce request frequency",
    1303: "concurrency/QPS exceeds prepaid resource package limit",
    1304: "IP not on whitelist — contact Kling support",
    5000: "Kling internal server error — retry later",
    5001: "Kling service temporarily unavailable (maintenance) — retry later",
    5002: "Kling server timeout (backlog) — retry later",
}


def _raise_for_service_code(http_status: int, body: dict[str, Any]) -> None:
    code = body.get("code", 0)
    if code == 0:
        return
    detail = body.get("message", "")
    friendly = _SERVICE_CODE_MESSAGES.get(code, f"unknown service code {code}")
    raise RuntimeError(
        f"Kling error {code} (HTTP {http_status}): {friendly}"
        + (f" — {detail}" if detail else "")
    )


def _first(data: Any) -> dict[str, Any]:
    """Extract the first item from a list-or-dict task response."""
    if isinstance(data, list) and data:
        return data[0]  # type: ignore[no-any-return]
    if isinstance(data, dict):
        items = data.get("list") or data.get("items") or []
        if items:
            return items[0]  # type: ignore[no-any-return]
    return {}


def _download(url: str, out_path: Path) -> None:
    with urllib.request.urlopen(url) as resp:
        out_path.write_bytes(resp.read())
