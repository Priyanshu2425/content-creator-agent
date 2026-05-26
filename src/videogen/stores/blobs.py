"""Blob paths: filesystem layout + single render-output writer, with an S3-later seam (Phase 7).

For v1 the storage mechanism is filesystem paths. All render outputs are written through this one
seam so that an S3-backed implementation can replace it later without touching callers. The full
store (snapshot undo/redo, append-only journal) is Phase 7; Phase 2 needs only a place to put the
mp4 and still that the backend produces.
"""

from __future__ import annotations

from pathlib import Path


class BlobStore:
    """Resolves names to on-disk output paths under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def output_path(self, name: str) -> Path:
        """Return the path a render output should be written to, ensuring its directory exists."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
