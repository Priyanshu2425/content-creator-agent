"""AuthoringService: the host of the authoring agent and the producer of the Composition (ADR 0003).

AuthoringService takes a Media Manifest (objective facts from MediaService) plus a free-text brief
and returns a finished, validated Composition ready for RenderService. It seeds a Builder from the
manifest's facts -- the voiceover master clock, the declared assets -- opens a CompositionStore for
the audit trail, and runs the authoring loop to drive the model through validated Builder ops.

When a video-capable ``ReviewAgent`` and a ``VideoRenderer`` are supplied, the service then runs the
Phase 8b finalization gate: the first-pass Composition is rendered to a full mp4, watched in motion,
and corrected through the *same* authoring loop, bounded by a round cap. Without them it behaves
exactly as Phase 8 -- a first valid pass with no full-motion review.

Per ADR 0003 the service depends only on the shared kernel and the ``agent``/finalization modules;
its one render-adjacent dependency is a ``RenderBackend`` *handle* (for the loop's in-loop
``render_still`` vision) plus an injected ``VideoRenderer`` seam -- it never imports a concrete
render engine or RenderService. The authoring model and the reviewer are both injected, so quality
vs. cost is the caller's choice without touching this service.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videogen import log
from videogen.agent import creation_styles
from videogen.agent.loop import DirectorLoop
from videogen.agent.model import ModelClient
from videogen.agent.perception import Manifest
from videogen.agent.review import ReviewAgent
from videogen.agent.vision_advice import VisionAdvisor
from videogen.backends.base import RenderBackend
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, Composition
from videogen.kernel.validator import ValidationResult
from videogen.services.finalize import FinalizationGate, FinalizationResult, VideoRenderer
from videogen.stores.composition_store import CompositionStore, JournalEntry


@dataclass(frozen=True)
class AuthoredComposition:
    """The output of an authoring run: the document, its validation report, how the loop ended,
    and the append-only audit journal of the ops the agent applied (story 34).

    When the finalization gate ran, ``video`` is the last reviewed mp4 and ``finalization`` carries
    the review trajectory; both are ``None`` for a Phase 8 first-pass-only run.
    """

    composition: Composition
    report: ValidationResult
    terminated_clean: bool
    ops_used: int
    journal: tuple[JournalEntry, ...]
    video: Path | None = None
    finalization: FinalizationResult | None = None


class AuthoringService:
    """Produces a Composition from a Manifest + brief by running the authoring agent loop.

    ``artifacts_dir`` is the per-run folder (``renders/<timestamp>/``) where the agent's
    intermediate artifacts -- stills/previews, the authored ``composition.json``, and the reviewer's
    per-round feedback -- are persisted. When ``None`` (the default, e.g. in unit tests) nothing is
    written to disk and behaviour is unchanged.
    """

    def __init__(
        self,
        *,
        backend: RenderBackend | None = None,
        artifacts_dir: Path | None = None,
        system: str | None = None,
    ) -> None:
        self._backend = backend
        self._artifacts_dir = artifacts_dir
        # The authoring system prompt (a creation style). ``None`` falls back to the active default
        # style at author time, so the choice lives in ``creation_styles.DEFAULT_STYLE``.
        self._system = system

    def author(
        self,
        manifest: Manifest,
        brief: str,
        *,
        model_client: ModelClient,
        reviewer: ReviewAgent | None = None,
        renderer: VideoRenderer | None = None,
        advisor: VisionAdvisor | None = None,
        max_ops: int = 40,
        max_review_rounds: int = 2,
        system: str | None = None,
        dispatchers: dict[str, Any] | None = None,
        brand_kit: Any = None,
        timeline_skeleton: str = "",
    ) -> AuthoredComposition:
        # Precedence: an explicit call argument, then the service's configured style, then the
        # active default style (``creation_styles.DEFAULT_STYLE``).
        system = system or self._system or creation_styles.active()
        builder = Builder.new(
            voiceover=manifest.voiceover,
            duration=manifest.duration,
            assets=_seed_assets(manifest),
        )
        store = CompositionStore()
        doc_id = store.open(builder.composition)
        loop = DirectorLoop(
            model_client,
            builder,
            manifest,
            store,
            doc_id,
            backend=self._backend,
            brief=brief,
            system=system,
            max_ops=max_ops,
            artifacts_dir=self._artifacts_dir,
            advisor=advisor,
            dispatchers=dispatchers,
            brand_kit=brand_kit,
            timeline_skeleton=timeline_skeleton,
        )
        result = loop.run()

        # Behavioral pacing pass (ADR 0008): the Director fills static gaps with content-free zoom
        # punch-ins before the document is reviewed/rendered. Pacing stays the Director's judgment,
        # not a kernel-enforced rule; this acts on the gaps the reconciler finds.
        from videogen.agent.pacing import analyze_pacing, fill_static_gaps

        filled = fill_static_gaps(builder, duration=manifest.duration)
        pacing_report = analyze_pacing(builder.composition, duration=manifest.duration)
        log.get().agent_event_complete(
            "pacing-pass",
            duration_ms=0,
            punch_ins_added=filled,
            remaining_gaps=len(pacing_report.gaps),
            collisions=len(pacing_report.collisions),
            safe_zone_violations=len(pacing_report.safe_zone_violations),
        )

        finalization: FinalizationResult | None = None
        if reviewer is not None and renderer is not None:
            finalization = FinalizationGate(
                client=model_client,
                builder=builder,
                manifest=manifest,
                store=store,
                doc_id=doc_id,
                reviewer=reviewer,
                renderer=renderer,
                backend=self._backend,
                system=system,
                max_ops=max_ops,
                max_rounds=max_review_rounds,
                artifacts_dir=self._artifacts_dir,
                advisor=advisor,
            ).run()

        if self._artifacts_dir is not None:
            self._artifacts_dir.mkdir(parents=True, exist_ok=True)
            (self._artifacts_dir / "composition.json").write_text(
                builder.composition.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
            )

        return AuthoredComposition(
            composition=builder.composition,
            report=builder.validate(),
            terminated_clean=result.terminated_clean,
            ops_used=result.ops_used,
            journal=store.journal(doc_id),
            video=finalization.video if finalization else None,
            finalization=finalization,
        )


def _seed_assets(manifest: Manifest) -> dict[str, Asset]:
    """Turn the manifest's objective asset facts into the Composition's declared asset library."""
    return {
        fact.id: Asset(type=AssetType(fact.type), src=fact.source) for fact in manifest.assets
    }
