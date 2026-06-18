"""Worker dispatch seam for the Director loop (ADR 0008).

A *worker dispatcher* is a callable the Director invokes mid-loop. It runs a specialist worker agent
and returns a ``WorkerProposal``: proposal text the Director reads, plus any new assets the worker
generated so the loop can register them into the Builder before the Director places them.

The loop stays decoupled from worker internals (media ingest, the b-roll agent, the image creator):
those are bound into the dispatcher at the service layer, so the loop only sees this thin seam and a
fake dispatcher makes the dispatch path unit-testable.

The ``Scratchpad`` is a shared mutable notepad visible to both the Director and every worker it
dispatches. The loop writes the Director's reasoning before each dispatch and the worker's proposal
after; dispatched workers receive the current scratchpad contents in their guidance so they can see
what the Director was thinking and what earlier workers already proposed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from videogen.kernel.composition import Asset, AssetId


@dataclass
class ScratchpadEntry:
    agent: str
    content: str


class Scratchpad:
    """Shared notepad between the Director and its dispatched workers.

    Every write is appended to ``log_path`` immediately (when set) so the full
    conversation between the Director and its workers is persisted to
    ``scratchpad.log`` alongside the other run artifacts.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._entries: list[ScratchpadEntry] = []
        self._log_path = log_path

    def write(self, agent: str, content: str) -> None:
        if not (content and content.strip()):
            return
        entry = ScratchpadEntry(agent=agent, content=content.strip())
        self._entries.append(entry)
        self._persist(entry)

    def read_all(self) -> str:
        if not self._entries:
            return "(scratchpad is empty)"
        lines = ["=== Shared Scratchpad ==="]
        for e in self._entries:
            lines.append(f"\n[{e.agent}]:\n{e.content}")
        return "\n".join(lines)

    @property
    def entries(self) -> list[ScratchpadEntry]:
        return list(self._entries)

    def _persist(self, entry: ScratchpadEntry) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n[{entry.agent}]\n{entry.content}\n{'─' * 60}\n")
        except OSError:
            pass


@dataclass(frozen=True)
class NewAsset:
    """An asset a worker produced, ready for the loop to register into the Builder library."""

    asset_id: AssetId
    asset: Asset
    description: str = ""


@dataclass(frozen=True)
class WorkerProposal:
    """What a dispatched worker returns to the Director: advisory text, any new assets, and any
    cut-bound SFX placements (scene_id -> sound) the loop applies via ``Builder.set_scene_audio``."""

    proposal_text: str
    new_assets: tuple[NewAsset, ...] = field(default_factory=tuple)
    scene_audio: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# Given a guidance dict (the Director's optional focus + the injected brand-kit tokens), produce a
# proposal. Implementations live at the service layer where media + the worker agent are available.
WorkerDispatcher = Callable[[dict[str, Any]], WorkerProposal]
