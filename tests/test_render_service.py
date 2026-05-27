"""RenderService: async submit_render -> job_id -> status -> artifact (Phase 7, ADR 0003).

The defining requirement: a multi-minute render must never block the Agent loop or a UI (ADR 0003).
These tests assert that external async contract -- submit returns a job_id promptly, polling moves a
job through running to a terminal state, a done job exposes an artifact that exists, a failure ends
as a terminal failed status (not a hang), the submit gate refuses a known-invalid Composition while
accepting one with only gap warnings, and concurrent jobs are tracked independently. The backend is
a fake `RenderBackend` so the job lifecycle is tested without invoking Node/Remotion; the
real-backend assertion lives in the render-path integration lane.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.backends.base import RenderBackend
from videogen.kernel.composition import Composition
from videogen.kernel.ir import IR
from videogen.services.render import JobState, RenderService
from videogen.stores.blobs import FilesystemBlobStore


class _FakeBackend:
    """A RenderBackend that just writes a marker file -- the job lifecycle without Node/Remotion."""

    def render_video(self, ir: IR, out_path: Path) -> Path:
        out_path.write_bytes(b"fake-mp4")
        return out_path

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:  # pragma: no cover - unused
        out_path.write_bytes(b"fake-png")
        return out_path


class _BlockingBackend(_FakeBackend):
    """Signals when a render starts and blocks until released, so a test can observe `running`."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def render_video(self, ir: IR, out_path: Path) -> Path:
        self.started.set()
        assert self.release.wait(timeout=5.0), "test did not release the blocking render"
        return super().render_video(ir, out_path)


class _FailingBackend:
    def render_video(self, ir: IR, out_path: Path) -> Path:
        raise RuntimeError("boom: the backend blew up mid-render")

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:  # pragma: no cover - unused
        raise RuntimeError("boom")


def _wait(
    service: RenderService,
    job_id: str,
    *,
    until: Callable[[object], bool],
    timeout: float = 5.0,
) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.status(job_id)
        if until(status):
            return status
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting; last status = {service.status(job_id)}")


@pytest.fixture
def comp(host_only_composition: Callable[..., Composition]) -> Composition:
    return host_only_composition(src="host.mp4", duration=2.0)


def _service(backend: RenderBackend, tmp_path: Path) -> RenderService:
    return RenderService(backend=backend, blobs=FilesystemBlobStore(tmp_path / "outputs"))


def test_submit_render_returns_a_job_id_and_the_job_completes_with_an_artifact(
    comp: Composition, tmp_path: Path
) -> None:
    with _service(_FakeBackend(), tmp_path) as service:
        job_id = service.submit_render(comp, fps=30, duration=2.0)
        assert isinstance(job_id, str) and job_id

        done = _wait(service, job_id, until=lambda s: s.state is JobState.done)  # type: ignore[attr-defined]
        assert done.artifact is not None and Path(done.artifact).exists()  # type: ignore[attr-defined]


def test_submit_render_does_not_block_for_the_render_duration(
    comp: Composition, tmp_path: Path
) -> None:
    backend = _BlockingBackend()
    with _service(backend, tmp_path) as service:
        started = time.monotonic()
        job_id = service.submit_render(comp, fps=30, duration=2.0)
        elapsed = time.monotonic() - started

        assert elapsed < 1.0  # returned immediately, while the render is still blocked
        assert backend.started.wait(timeout=5.0)  # the worker is rendering in the background
        assert service.status(job_id).state is not JobState.done  # not finished while blocked

        backend.release.set()
        _wait(service, job_id, until=lambda s: s.state is JobState.done)  # type: ignore[attr-defined]


def test_progress_advances_while_running_and_reaches_one_when_done(
    comp: Composition, tmp_path: Path
) -> None:
    backend = _BlockingBackend()
    with _service(backend, tmp_path) as service:
        job_id = service.submit_render(comp, fps=30, duration=2.0)
        assert backend.started.wait(timeout=5.0)

        running = service.status(job_id)
        assert running.state is JobState.running
        assert 0.0 < running.progress < 1.0  # movement on a long render, before it finishes

        backend.release.set()
        done = _wait(service, job_id, until=lambda s: s.state is JobState.done)  # type: ignore[attr-defined]
        assert done.progress == 1.0  # type: ignore[attr-defined]


def test_a_backend_failure_ends_as_a_terminal_failed_status_not_a_hang(
    comp: Composition, tmp_path: Path
) -> None:
    with _service(_FailingBackend(), tmp_path) as service:
        job_id = service.submit_render(comp, fps=30, duration=2.0)

        failed = _wait(service, job_id, until=lambda s: s.state is JobState.failed)  # type: ignore[attr-defined]
        assert failed.error and "boom" in failed.error  # type: ignore[attr-defined]
        assert failed.artifact is None  # type: ignore[attr-defined]


def test_submit_refuses_a_composition_that_fails_the_validation_gate(
    comp: Composition, tmp_path: Path
) -> None:
    """A scene ending past the (shorter) voiceover is a local error -- refuse, don't render."""
    with _service(_FakeBackend(), tmp_path) as service, pytest.raises(ValueError):
        service.submit_render(comp, fps=30, duration=1.0)  # scene end 2.0 > duration 1.0


def test_submit_accepts_a_composition_with_only_gap_warnings(
    comp: Composition, tmp_path: Path
) -> None:
    """A trailing gap warns but does not block (Phase 4 coverage rules); the render still runs."""
    with _service(_FakeBackend(), tmp_path) as service:
        job_id = service.submit_render(comp, fps=30, duration=3.0)  # scene [0,2], gap [2,3]

        done = _wait(service, job_id, until=lambda s: s.state is JobState.done)  # type: ignore[attr-defined]
        assert Path(done.artifact).exists()  # type: ignore[attr-defined]


def test_concurrent_jobs_are_tracked_independently(comp: Composition, tmp_path: Path) -> None:
    with _service(_FakeBackend(), tmp_path) as service:
        job_ids = [service.submit_render(comp, fps=30, duration=2.0) for _ in range(4)]

        assert len(set(job_ids)) == 4  # each submission gets its own id
        artifacts = set()
        for job_id in job_ids:
            done = _wait(service, job_id, until=lambda s: s.state is JobState.done)  # type: ignore[attr-defined]
            assert Path(done.artifact).exists()  # type: ignore[attr-defined]
            artifacts.add(done.artifact)  # type: ignore[attr-defined]
        assert len(artifacts) == 4  # distinct outputs, not one clobbering another
