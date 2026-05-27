"""Blob storage: the single render-output writer behind an S3-later seam (Phase 7, ADR 0003).

There is exactly one place a finished render is persisted to storage, so the storage backend can
move to S3 later behind one seam rather than a caller rewrite (plan's S3-later deferral). The seam
is the ``BlobStore`` protocol; ``write_render_output`` takes a finished *local* file (the backend
renders to a scratch path it can write to) and persists it, returning a retrievable *location* --
a path string today, an ``s3://`` URI under a future implementation. Callers (the RenderService
worker) hold the artifact only as that opaque location, never as a filesystem assumption.

For v1 the only implementation is ``FilesystemBlobStore``; S3 is out of scope (plan), but the
protocol is shaped so an S3 writer is an added class, not a change to the worker.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    """The single render-output writer (ADR 0003 storage seam). One concrete impl in v1."""

    def write_render_output(self, name: str, source: Path) -> str:
        """Persist the finished render ``source`` under ``name``; return its retrievable location.

        ``source`` is a local file the backend produced; the returned location is opaque to callers
        (a filesystem path today, an object-store URI later).
        """
        ...


class FilesystemBlobStore:
    """Persists render outputs under a root directory; the location is the absolute file path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_render_output(self, name: str, source: Path) -> str:
        dest = self.root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return str(dest.resolve())
