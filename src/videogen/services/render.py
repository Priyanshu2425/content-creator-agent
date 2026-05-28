"""RenderService: async submit_render -> job_id -> status -> artifact (Phase 7, ADR 0003).

The defining requirement (ADR 0003): a multi-minute render must never block the Agent loop or a UI.
So ``submit_render`` validates against the Phase 4 submit gate, enqueues the work on a background
worker, and returns a ``job_id`` immediately; callers poll ``status(job_id)`` for progress and,
when done, the artifact's location. The worker runs the existing Composition -> IR (``compile_ir``,
driving plugins via the registry) -> backend (``render_video``) pipeline and persists the finished
artifact through the single render-output writer in ``stores/blobs.py``.

Monolith-first (ADR 0003): the concurrency is a ``ThreadPoolExecutor`` plus an in-memory job
registry, with no external queue. The surface is shaped so that swapping in a real distributed
queue later is a transport change, not a redesign. The registry is guarded by a lock so worker
threads and pollers never see a torn job record. The fast ``render_still`` path stays synchronous
on the backend and is deliberately *not* routed through this async lifecycle (ADR 0002/0004:
Phase 8's in-loop vision needs cheap stills, not minute-long jobs).
"""

from __future__ import annotations

import dataclasses
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType

from videogen.backends.base import RenderBackend
from videogen.backends.remotion import RemotionBackend
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Composition
from videogen.kernel.validator import validate_local
from videogen.stores.blobs import BlobStore, FilesystemBlobStore


class JobState(StrEnum):
    """The lifecycle of a render job; ``done`` and ``failed`` are terminal."""

    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass(frozen=True)
class JobStatus:
    """An immutable snapshot of a job, returned to pollers (never a live, mutating record)."""

    id: str
    state: JobState
    progress: float = 0.0
    artifact: str | None = None  # the blob-store location, set once done
    error: str | None = None  # set once failed


# Coarse progress milestones: the backend render is an opaque subprocess, so progress moves at the
# pipeline's phase boundaries rather than per-frame -- enough for a poller to see a job advance.
_PROGRESS_COMPILED = 0.3
_PROGRESS_RENDERED = 0.9


class RenderService:
    """Async render jobs over a ThreadPoolExecutor + in-memory registry (monolith-first)."""

    def __init__(
        self,
        backend: RenderBackend | None = None,
        blobs: BlobStore | None = None,
        *,
        max_workers: int = 2,
    ) -> None:
        self._backend: RenderBackend = backend or RemotionBackend()
        self._blobs: BlobStore = blobs or FilesystemBlobStore(Path("renders"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()

    def submit_render(
        self, composition: Composition, *, fps: int, duration: float, name: str | None = None
    ) -> str:
        """Validate against the submit gate, enqueue the render, and return a ``job_id`` at once.

        Reported local errors (overlaps, out-of-bounds scenes, dangling refs) block here so a known-
        invalid Composition never spends minutes rendering; gap warnings do not block (Phase 4).

        ``name`` is the output filename to persist under (e.g. ``round-1.mp4``, ``final.mp4``);
        when omitted it defaults to ``<job_id>.mp4``, the prior behaviour.
        """
        errors = validate_local(composition, duration=duration)
        if errors:
            joined = "; ".join(f"{e.code}: {e.message}" for e in errors)
            raise ValueError(f"composition fails the render submit gate: {joined}")

        job_id = uuid.uuid4().hex
        out_name = name or f"{job_id}.mp4"
        with self._lock:
            self._jobs[job_id] = JobStatus(id=job_id, state=JobState.queued)
        self._executor.submit(self._run, job_id, composition, fps, duration, out_name)
        return job_id

    def status(self, job_id: str) -> JobStatus:
        """The current immutable snapshot of a job (thread-safe read)."""
        with self._lock:
            return self._jobs[job_id]

    def close(self) -> None:
        """Shut the worker pool down; in-flight jobs finish first."""
        self._executor.shutdown(wait=True)

    def __enter__(self) -> RenderService:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- worker ---

    def _run(
        self, job_id: str, composition: Composition, fps: int, duration: float, out_name: str
    ) -> None:
        try:
            self._set(job_id, state=JobState.running, progress=0.05)
            ir = compile_ir(composition, fps=fps, duration=duration)
            self._set(job_id, progress=_PROGRESS_COMPILED)
            with tempfile.TemporaryDirectory() as scratch:
                rendered = self._backend.render_video(ir, Path(scratch) / out_name)
                self._set(job_id, progress=_PROGRESS_RENDERED)
                location = self._blobs.write_render_output(out_name, rendered)
            self._set(job_id, state=JobState.done, progress=1.0, artifact=location)
        except Exception as exc:  # noqa: BLE001 - any failure becomes a terminal failed status
            self._set(job_id, state=JobState.failed, error=str(exc))

    def _set(self, job_id: str, **changes: object) -> None:
        """Atomically replace a job's snapshot with an updated one (registry stays untorn)."""
        with self._lock:
            self._jobs[job_id] = dataclasses.replace(self._jobs[job_id], **changes)  # type: ignore[arg-type]


class RenderServiceRenderer:
    """A ``VideoRenderer`` (the Phase 8b finalization seam) backed by RenderService's job lifecycle.

    The finalization gate needs a finished mp4 to review but must not know about RenderService
    (ADR 0003 boundary): it depends only on the ``VideoRenderer`` Protocol in ``services.finalize``.
    This adapter is the one place that bridges the two -- it submits the render, polls the job to a
    terminal state, and returns the artifact's path, so the gate calls one method and gets a file
    without ever touching the async job API. It is constructed and injected by the CLI (Phase 9);
    AuthoringService never imports it, keeping the service boundary intact. The same submit gate
    RenderService enforces still refuses a known-invalid Composition before any render runs.
    """

    def __init__(
        self,
        service: RenderService,
        *,
        timeout: float = 600.0,
        poll_interval: float = 0.25,
    ) -> None:
        self._service = service
        self._timeout = timeout
        self._poll_interval = poll_interval

    def render_video(
        self, composition: Composition, *, fps: int, duration: float, name: str | None = None
    ) -> Path:
        """Render ``composition`` to an mp4 via the async job, blocking until it is done.

        Returns the finished artifact's path. Raises if the job fails or does not finish within the
        timeout, so a stuck render surfaces as an error rather than wedging the finalization loop.
        ``name`` labels the output file (e.g. ``round-1.mp4``); defaults to ``<job_id>.mp4``.
        """
        job_id = self._service.submit_render(composition, fps=fps, duration=duration, name=name)
        deadline = time.monotonic() + self._timeout
        while True:
            status = self._service.status(job_id)
            if status.state is JobState.done:
                assert status.artifact is not None  # a done job always carries its artifact
                return Path(status.artifact)
            if status.state is JobState.failed:
                raise RuntimeError(f"render job {job_id} failed: {status.error}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"render job {job_id} did not finish within {self._timeout}s")
            time.sleep(self._poll_interval)

    def close(self) -> None:
        """Shut the underlying RenderService's worker pool down (in-flight jobs finish first)."""
        self._service.close()
