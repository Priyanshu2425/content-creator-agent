"""RemotionBackend: Python subprocess wrapper around the Node project in ./project (Phase 2).

Shells out to `npx remotion render` / `still`, passing the IR as --props JSON (ADR 0002).

This is the only component aware of the Node toolchain. It owns: serializing the IR to props,
staging referenced media into a public dir so Remotion's `staticFile` can resolve it, the
frame-rate-aware seconds->frame mapping for stills, invoking the Remotion CLI, and surfacing
subprocess failures as Python errors. It implements both methods of the RenderBackend protocol --
`render_still` is built now because the Phase 8 authoring loop depends on a cheap single frame,
and proving it is nearly free once `render_video` works.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from videogen.kernel.ir import IR


class RemotionBackend:
    """Drives the co-located Remotion Node app to turn an IR into an mp4 or a single still."""

    PROJECT_DIR = Path(__file__).resolve().parent / "project"
    ENTRY = "src/index.ts"
    COMPOSITION_ID = "Main"

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = project_dir or self.PROJECT_DIR

    def render_video(self, ir: IR, out_path: Path) -> Path:
        """Render the IR to a video at `out_path` (mp4 inferred from the extension)."""
        return self._invoke("render", ir, Path(out_path), extra=[])

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:
        """Render a single frame at time `t` seconds to `out_path`."""
        # Same seconds->frames rule the Remotion side uses, so the still lands on the right frame.
        frame = round(t * ir.fps)
        return self._invoke("still", ir, Path(out_path), extra=[f"--frame={frame}"])

    # --- internals ---

    def _invoke(self, command: str, ir: IR, out_path: Path, *, extra: list[str]) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / "public"
            public.mkdir()
            payload = self._stage_assets(ir, public)
            props = Path(tmp) / "props.json"
            props.write_text(json.dumps({"ir": payload}))

            argv = [
                "npx",
                "remotion",
                command,
                self.ENTRY,
                self.COMPOSITION_ID,
                str(out_path),
                f"--props={props}",
                f"--public-dir={public}",
                *extra,
            ]
            result = subprocess.run(
                argv, cwd=self.project_dir, capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"remotion {command} failed (exit {result.returncode}).\n"
                    f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
                )
        if not out_path.exists():
            raise RuntimeError(
                f"remotion {command} exited 0 but produced no file at {out_path}"
            )
        return out_path

    def _stage_assets(self, ir: IR, public: Path) -> dict[str, Any]:
        """Stage each referenced media file into `public`; rewrite layer srcs to staticFile names.

        The IR carries resolved paths; Remotion's `staticFile` resolves names against the public
        dir, so we link the real bytes in under a collision-safe name and hand Remotion the name.
        """
        payload: dict[str, Any] = ir.model_dump(by_alias=True)
        staged: dict[str, str] = {}
        for layer in payload["layers"]:
            src = layer.get("src")
            if not src:
                continue
            if src not in staged:
                staged[src] = self._stage_one(Path(src), public)
            layer["src"] = staged[src]
        return payload

    @staticmethod
    def _stage_one(src: Path, public: Path) -> str:
        src = src.resolve()
        # Prefix with a short hash of the full path so distinct sources never collide on basename.
        name = f"{hashlib.sha256(str(src).encode()).hexdigest()[:8]}_{src.name}"
        target = public / name
        if not target.exists():
            # Copy rather than symlink: Remotion copies the public dir into its webpack bundle, and
            # a symlink does not survive that copy (the served path 404s).
            shutil.copy2(src, target)
        return name
