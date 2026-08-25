"""Re-render the most recent run's Composition (no LLM) to verify caption placement changes."""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from videogen.backends.remotion import RemotionBackend
from videogen.kernel.composition import Composition
from videogen.services.render import RenderService, RenderServiceRenderer
from videogen.stores.blobs import FilesystemBlobStore


def main() -> None:
    runs = [p for p in glob.glob("renders/*/final.composition.json")]
    run_dir = str(Path(max(runs, key=os.path.getmtime)).parent) + "/"
    comp = Composition.model_validate_json(Path(run_dir, "final.composition.json").read_text())
    ir = json.loads(Path(run_dir, "final.ir.json").read_text())
    fps = int(ir.get("fps", 30))
    duration = float(ir.get("duration") or max((s.end for s in comp.scenes), default=1.0))

    out_dir = Path("renders/caption-top-example")
    out_dir.mkdir(parents=True, exist_ok=True)
    renderer = RenderServiceRenderer(
        RenderService(backend=RemotionBackend(), blobs=FilesystemBlobStore(out_dir))
    )
    artifact = renderer.render_video(comp, fps=fps, duration=duration, name="caption_top.mp4")
    print(f"source run : {run_dir}")
    print(f"captions   : {len(comp.captions)} (style {comp.captions[0].style if comp.captions else 'none'})")
    print(f"rendered   : {artifact}")


if __name__ == "__main__":
    main()
