"""`videogen preview <run>`: open a finished run in the browser via Remotion Studio.

A pipeline run persists the final compiled IR next to its mp4 (``<run>/final.ir.json``). The same IR
drives the renderer and the Remotion ``Main`` composition, so we can show the exact final video in
the browser without re-rendering. The one extra step is media: the browser resolves assets from the
Remotion project's ``public/`` dir, while the persisted IR carries resolved source paths -- so this
stages each referenced file into ``public/preview/`` (reusing the backend's collision-safe staging)
and rewrites the layer ``src`` fields, then writes the staged IR to ``public/preview-ir.json`` where
the ``Main`` composition's ``calculateMetadata`` loads it. Finally it launches ``remotion studio``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from videogen.backends.remotion import RemotionBackend

_PREVIEW_SUBDIR = "preview"
_PREVIEW_PROPS = "preview-ir.json"


def resolve_ir_json(arg: str | Path) -> Path:
    """Resolve the ``preview`` argument to an IR JSON file.

    Accepts a direct ``*.ir.json`` path or a run directory; for a directory it prefers
    ``final.ir.json`` and otherwise picks the most recently modified ``*.ir.json``.
    """
    path = Path(arg).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        final = path / "final.ir.json"
        if final.is_file():
            return final
        candidates = sorted(path.glob("*.ir.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"no *.ir.json found in run directory {path}")
    raise FileNotFoundError(f"not a file or directory: {arg}")


def stage_preview_payload(ir_payload: dict[str, Any], public_root: Path) -> dict[str, Any]:
    """Stage every media file the IR references into ``public_root/preview/`` and rewrite each layer
    ``src`` to a ``preview/<name>`` staticFile path. Returns the rewritten ``{"ir": payload}`` wrapper
    the Main composition consumes. Missing source files are left as-is (the layer will 404 in the
    browser but the rest of the preview still renders)."""
    stage_dir = public_root / _PREVIEW_SUBDIR
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged: dict[str, str] = {}
    for layer in ir_payload.get("layers", []):
        src = layer.get("src")
        if not src:
            continue
        if src not in staged:
            source = Path(src)
            if not source.exists():
                staged[src] = src  # leave unresolved; don't crash the whole preview
                continue
            staged[src] = f"{_PREVIEW_SUBDIR}/{RemotionBackend._stage_one(source, stage_dir)}"
        layer["src"] = staged[src]
    return {"ir": ir_payload}


def run_preview(arg: str | Path, *, project_dir: Path | None = None) -> int:
    """Stage a run's assets, write the preview props, and launch Remotion Studio (foreground)."""
    project = project_dir or RemotionBackend.PROJECT_DIR
    ir_json = resolve_ir_json(arg)
    payload = json.loads(ir_json.read_text(encoding="utf-8"))
    # Tolerate either a bare IR or an already-wrapped {"ir": ...}.
    ir_payload = payload["ir"] if isinstance(payload, dict) and "ir" in payload else payload

    public_root = project / "public"
    staged = stage_preview_payload(ir_payload, public_root)
    (public_root / _PREVIEW_PROPS).write_text(json.dumps(staged), encoding="utf-8")

    print(f"videogen: previewing {ir_json} in Remotion Studio (Ctrl-C to stop)…")
    return subprocess.run(["npx", "remotion", "studio"], cwd=project).returncode
