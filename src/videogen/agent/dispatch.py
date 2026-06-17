"""Worker dispatch seam for the Director loop (ADR 0008).

A *worker dispatcher* is a callable the Director invokes mid-loop. It runs a specialist worker agent
and returns a ``WorkerProposal``: proposal text the Director reads, plus any new assets the worker
generated so the loop can register them into the Builder before the Director places them.

The loop stays decoupled from worker internals (media ingest, the b-roll agent, the image creator):
those are bound into the dispatcher at the service layer, so the loop only sees this thin seam and a
fake dispatcher makes the dispatch path unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from videogen.kernel.composition import Asset, AssetId


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
