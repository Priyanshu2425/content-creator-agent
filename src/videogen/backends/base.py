"""RenderBackend protocol: render_video / render_still (IR -> frames) (Phase 2).

A backend turns the neutral IR into frames (ADR 0002). It is the only component aware of a
specific render engine; everything upstream -- the Composition, `compile_ir`, the plugins --
stays backend-agnostic. Declaring the contract as a Protocol means a second backend
(`FfmpegBackend` or a custom engine) can be slotted in later as a single new IR interpreter
without changing any caller. RemotionBackend is the first and only implementation this phase.

`render_still` is part of the contract from the start because the authoring loop in Phase 8
depends on a cheap single-frame render to see its work without a full video render.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from videogen.kernel.ir import IR


class RenderBackend(Protocol):
    """Interprets the IR's layer kinds and emits frames. The seam for future backends (ADR 0002)."""

    def render_video(self, ir: IR, out_path: Path) -> Path:
        """Render the IR to a video file at `out_path` and return that path."""
        ...

    def render_still(self, ir: IR, t: float, out_path: Path) -> Path:
        """Render a single frame at time `t` (seconds) to `out_path` and return that path."""
        ...
