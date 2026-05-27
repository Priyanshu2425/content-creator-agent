"""blobs: the single render-output writer behind an S3-later seam (Phase 7, ADR 0003).

These tests assert the externally observable contract -- a finished render handed to the writer
lands at a retrievable location, and the surface is an interface a non-filesystem writer can stand
in for -- not the on-disk path scheme. The seam exists so a later S3 writer is an added
implementation, not a caller rewrite (plan's S3-later deferral); the test proves a fake writer
satisfies the same `BlobStore` protocol the RenderService depends on.
"""

from __future__ import annotations

from pathlib import Path

from videogen.stores.blobs import BlobStore, FilesystemBlobStore


def test_filesystem_writer_persists_a_finished_render_at_a_retrievable_location(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scratch" / "render.mp4"
    source.parent.mkdir()
    source.write_bytes(b"mp4-bytes")
    store = FilesystemBlobStore(tmp_path / "outputs")

    location = store.write_render_output("job-123.mp4", source)

    persisted = Path(location)
    assert persisted.exists()
    assert persisted.read_bytes() == b"mp4-bytes"  # the finished render reached storage intact


def test_the_writer_creates_its_output_root_on_demand(tmp_path: Path) -> None:
    source = tmp_path / "render.mp4"
    source.write_bytes(b"x")
    store = FilesystemBlobStore(tmp_path / "does" / "not" / "exist")

    location = store.write_render_output("out.mp4", source)

    assert Path(location).exists()  # the writer owns making its destination, not the caller


def test_a_fake_writer_satisfies_the_seam() -> None:
    """The S3-later seam: any object honoring `BlobStore` can replace the filesystem writer."""

    class FakeBlobStore:
        def __init__(self) -> None:
            self.written: list[tuple[str, Path]] = []

        def write_render_output(self, name: str, source: Path) -> str:
            self.written.append((name, source))
            return f"s3://bucket/{name}"

    store: BlobStore = FakeBlobStore()
    location = store.write_render_output("job-9.mp4", Path("/tmp/render.mp4"))

    assert location == "s3://bucket/job-9.mp4"
    assert store.written == [("job-9.mp4", Path("/tmp/render.mp4"))]  # type: ignore[attr-defined]
