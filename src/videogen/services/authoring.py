"""AuthoringService: the host of the authoring agent and the producer of the Composition (ADR 0003).

AuthoringService takes a Media Manifest (objective facts from MediaService) plus a free-text brief
and returns a finished, validated Composition ready for RenderService. It seeds a Builder from the
manifest's facts -- the voiceover master clock, the declared assets -- opens a CompositionStore for
the audit trail, and runs the authoring loop to drive the model through validated Builder ops.

Per ADR 0003 the service depends only on the shared kernel and the ``agent`` module; its one
render-adjacent dependency is a ``RenderBackend`` *handle*, used solely for the loop's in-loop
vision (``render_still``) -- it never imports a concrete render engine or RenderService. The model
is injected as a ``ModelClient`` (the swappable seam), so authoring quality vs cost is the caller's
choice without touching this service.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.loop import AuthoringLoop
from videogen.agent.model import ModelClient
from videogen.agent.perception import Manifest
from videogen.agent.prompts import SYSTEM_PROMPT
from videogen.backends.base import RenderBackend
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, Composition
from videogen.kernel.validator import ValidationResult
from videogen.stores.composition_store import CompositionStore, JournalEntry


@dataclass(frozen=True)
class AuthoredComposition:
    """The output of an authoring run: the document, its validation report, how the loop ended,
    and the append-only audit journal of the ops the agent applied (story 34)."""

    composition: Composition
    report: ValidationResult
    terminated_clean: bool
    ops_used: int
    journal: tuple[JournalEntry, ...]


class AuthoringService:
    """Produces a Composition from a Manifest + brief by running the authoring agent loop."""

    def __init__(self, *, backend: RenderBackend | None = None) -> None:
        self._backend = backend

    def author(
        self,
        manifest: Manifest,
        brief: str,
        *,
        model_client: ModelClient,
        max_ops: int = 40,
        system: str = SYSTEM_PROMPT,
    ) -> AuthoredComposition:
        builder = Builder.new(
            voiceover=manifest.voiceover,
            duration=manifest.duration,
            assets=_seed_assets(manifest),
        )
        store = CompositionStore()
        doc_id = store.open(builder.composition)
        loop = AuthoringLoop(
            model_client,
            builder,
            manifest,
            store,
            doc_id,
            backend=self._backend,
            brief=brief,
            system=system,
            max_ops=max_ops,
        )
        result = loop.run()
        return AuthoredComposition(
            composition=result.composition,
            report=result.report,
            terminated_clean=result.terminated_clean,
            ops_used=result.ops_used,
            journal=store.journal(doc_id),
        )


def _seed_assets(manifest: Manifest) -> dict[str, Asset]:
    """Turn the manifest's objective asset facts into the Composition's declared asset library."""
    return {
        fact.id: Asset(type=AssetType(fact.type), src=fact.source) for fact in manifest.assets
    }
