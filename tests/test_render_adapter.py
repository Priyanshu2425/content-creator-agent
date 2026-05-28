"""RenderServiceRenderer: the in-process VideoRenderer that bridges the gate to RenderService.

The Phase 8b finalization gate depends only on the ``VideoRenderer`` seam (a Composition in, an
mp4 path out); it must not know about RenderService's async job lifecycle (ADR 0003 boundary).
This adapter is the one place that bridges the two. These tests assert its external contract over a
fake backend: a submitted render is polled to completion and its artifact path returned; a backend
failure surfaces as an error rather than a hang; an unrenderable Composition is refused by the same
submit gate the service enforces -- all without invoking Node/Remotion.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.kernel.composition import Composition
from videogen.kernel.ir import IR
from videogen.services.render import RenderService, RenderServiceRenderer
from videogen.stores.blobs import FilesystemBlobStore


class _FakeBackend:
    """Writes a marker mp4 so the job lifecycle runs without Node/Remotion."""

    def render_video(self, ir: IR, out_path: Path) -> Path:
        out_path.write_bytes(b"fake-mp4")
        return out_path

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:  # pragma: no cover - unused
        out_path.write_bytes(b"fake-png")
        return out_path


class _FailingBackend(_FakeBackend):
    def render_video(self, ir: IR, out_path: Path) -> Path:
        raise RuntimeError("boom: the backend blew up mid-render")


@pytest.fixture
def comp(host_only_composition: Callable[..., Composition]) -> Composition:
    return host_only_composition(src="host.mp4", duration=2.0)


def _renderer(backend: object, tmp_path: Path) -> tuple[RenderService, RenderServiceRenderer]:
    service = RenderService(backend=backend, blobs=FilesystemBlobStore(tmp_path / "out"))  # type: ignore[arg-type]
    return service, RenderServiceRenderer(service)


def test_render_video_submits_polls_and_returns_the_finished_artifact(
    comp: Composition, tmp_path: Path
) -> None:
    service, renderer = _renderer(_FakeBackend(), tmp_path)
    with service:
        out = renderer.render_video(comp, fps=30, duration=2.0)

    assert out.exists() and out.stat().st_size > 0  # the gate gets a real file back
    assert out.suffix == ".mp4"


def test_render_video_raises_when_the_job_fails_rather_than_hanging(
    comp: Composition, tmp_path: Path
) -> None:
    service, renderer = _renderer(_FailingBackend(), tmp_path)
    with service, pytest.raises(RuntimeError, match="boom"):
        renderer.render_video(comp, fps=30, duration=2.0)


def test_render_video_refuses_a_composition_that_fails_the_submit_gate(
    comp: Composition, tmp_path: Path
) -> None:
    """A scene ending past the (shorter) voiceover is a local error -- the same gate RenderService
    enforces refuses it before any render, so an invalid Composition never reaches the backend."""
    service, renderer = _renderer(_FakeBackend(), tmp_path)
    with service, pytest.raises(ValueError):
        renderer.render_video(comp, fps=30, duration=1.0)  # scene end 2.0 > duration 1.0
