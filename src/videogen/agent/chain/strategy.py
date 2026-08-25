"""Authoring strategies: the swappable back half of a Pipeline (ADR 0013).

Both pipelines share the front half (ingest -> transcribe -> ideal-cuts). The *back half* -- how the
Composition is authored -- is a strategy:

- ``DirectorLoopStrategy`` (default) runs the adaptive Director loop (ADR 0008) that pulls workers on
  demand and authors op-by-op.
- ``ChainStrategy`` runs the workers in a fixed order and lets the Composer emit the Composition.

Both call the *same* worker dispatchers (the shared seam), so the only variable under the A/B is the
topology, not the workers. The chain owns the per-stage failure policy: creative direction and the
Composer are fatal; b-roll, motion-graphics, text-hook are degradable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

from videogen import log
from videogen.agent.beat_plan import Beat, BeatPlan
from videogen.agent.chain.composer import Composer, ComposerError
from videogen.agent.chain.config import ChainConfig
from videogen.agent.chain.prep import prep
from videogen.agent.chain.reconcile import reconcile
from videogen.agent.dispatch import NewAsset, WorkerDispatcher
from videogen.agent.model import ModelClient
from videogen.agent.perception import Manifest
from videogen.kernel.composition import Composition, Hook

# Beat kinds routed to each generator. b-roll covers stills + stat-viz; motion-graphics covers animated
# text/graphics. host-aroll needs no generation (it binds the existing host track).
_BROLL_KINDS = frozenset({"broll-image", "broll-video", "stat-viz"})
_MG_KINDS = frozenset({"motion-graphic"})


class ChainStageError(RuntimeError):
    """A fatal failure at a named chain stage. The CLI re-raises it as a stage-named PipelineError."""

    def __init__(self, stage: str, cause: BaseException) -> None:
        super().__init__(f"{stage}: {cause}")
        self.stage = stage
        self.cause = cause


class AuthoringStrategy(Protocol):
    """The seam at the pipeline fork: prepared front-half inputs -> a finished Composition."""

    def author(
        self,
        *,
        manifest: Manifest,
        brief: str,
        dispatchers: dict[str, WorkerDispatcher],
        brand_kit_tokens: dict[str, Any] | None,
    ) -> Composition: ...


@dataclass
class DirectorLoopStrategy:
    """The default back half (ADR 0008): the adaptive Director loop, run via AuthoringService.

    It pulls workers on demand and authors op-by-op. This realizes the strategy seam over the existing
    AuthoringService; the director-loop's extra collaborators (reviewer/renderer/advisor/skeleton/
    brand kit) are held as fields so ``author`` matches the strategy signature. ``brand_kit_tokens`` is
    accepted for protocol symmetry but ignored -- the loop receives the full BrandKit object."""

    authoring: Any  # AuthoringService
    model_client: ModelClient
    reviewer: Any = None
    renderer: Any = None
    advisor: Any = None
    max_review_rounds: int = 2
    brand_kit: Any = None
    timeline_skeleton: str = ""

    def author(
        self,
        *,
        manifest: Manifest,
        brief: str,
        dispatchers: dict[str, WorkerDispatcher],
        brand_kit_tokens: dict[str, Any] | None = None,
    ) -> Composition:
        authored = self.authoring.author(
            manifest,
            brief,
            model_client=self.model_client,
            reviewer=self.reviewer,
            renderer=self.renderer,
            advisor=self.advisor,
            max_review_rounds=self.max_review_rounds,
            dispatchers=dispatchers or None,
            brand_kit=self.brand_kit,
            timeline_skeleton=self.timeline_skeleton,
        )
        return authored.composition


@dataclass
class ChainStrategy:
    """The fixed-order chain (ADR 0013): creative direction -> {b-roll, motion-graphics, text-hook}
    in parallel -> prep -> Composer. SFX is the pipeline's post-Composer stage, not part of this."""

    model_client: ModelClient
    config: ChainConfig = field(default_factory=ChainConfig)
    composer: Composer | None = None

    def author(
        self,
        *,
        manifest: Manifest,
        brief: str,
        dispatchers: dict[str, WorkerDispatcher],
        brand_kit_tokens: dict[str, Any] | None,
    ) -> Composition:
        beat_plan = self._creative_direction(dispatchers, brand_kit_tokens)
        beat_keyed, extra, hook = self._generate(dispatchers, brand_kit_tokens, beat_plan)
        resolved = prep(beat_plan, beat_keyed, manifest.transcript)

        composer = self.composer or Composer(client=self.model_client)
        try:
            composition = composer.compose(
                manifest=manifest,
                brief=brief,
                resolved_beats=resolved,
                brand_kit_tokens=brand_kit_tokens,
                extra_assets=tuple(extra),
            )
        except ComposerError as exc:  # fatal: the Composer IS the artifact (ADR 0013)
            raise ChainStageError("compose", exc) from exc

        # Deterministic post-Composer reconcile (ADR 0013): the kernel-level hook (the text-hook
        # worker's authoritative output), base captions (suppressed under the hook window), and
        # animate stills. The Composer never places the hook.
        style = (brand_kit_tokens or {}).get("caption_style", "tiktok")
        return reconcile(
            composition,
            transcript=manifest.transcript,
            duration=manifest.duration,
            caption_style=style if isinstance(style, str) else "tiktok",
            hook=hook,
        )

    # --- stages -----------------------------------------------------------------------------------

    def _creative_direction(
        self, dispatchers: dict[str, WorkerDispatcher], tokens: dict[str, Any] | None
    ) -> BeatPlan:
        """Fatal stage: no BeatPlan means nothing downstream can run (ADR 0013)."""
        dispatch = dispatchers.get("dispatch_creative_direction")
        if dispatch is None:
            raise ChainStageError("creative-direction", RuntimeError("no creative-direction worker wired"))
        try:
            proposal = dispatch({"brand_kit": tokens, "guidance": ""})
        except Exception as exc:
            raise ChainStageError("creative-direction", exc) from exc
        plan = proposal.beat_plan
        if plan is None or not plan.beats:
            raise ChainStageError(
                "creative-direction", RuntimeError("worker returned no BeatPlan")
            )
        return plan

    def _generate(
        self,
        dispatchers: dict[str, WorkerDispatcher],
        tokens: dict[str, Any] | None,
        beat_plan: BeatPlan,
    ) -> tuple[list[NewAsset], list[NewAsset], Hook | None]:
        """Run b-roll, motion-graphics and text-hook in parallel. Each is degradable: a failure logs
        and yields nothing rather than failing the run. Returns (beat-keyed assets, extra unbound
        assets, the hook)."""
        broll_beats = [b for b in beat_plan.beats if b.asset_spec.kind in _BROLL_KINDS]
        mg_beats = [b for b in beat_plan.beats if b.asset_spec.kind in _MG_KINDS]

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_broll = pool.submit(
                self._degradable_assets, dispatchers, "dispatch_broll", tokens, broll_beats
            )
            f_mg = pool.submit(
                self._degradable_assets, dispatchers, "dispatch_motion_graphics", tokens, mg_beats
            )
            # The opening hook is disabled by default (ADR 0013): only dispatch the text-hook worker
            # and attach a hook when hook_enabled. Otherwise no text-hook call, no composition.hook.
            f_hook = (
                pool.submit(self._degradable_hook, dispatchers, tokens)
                if self.config.hook_enabled
                else None
            )
            assets = list(f_broll.result()) + list(f_mg.result())
            hook = f_hook.result() if f_hook is not None else None

        beat_keyed = [na for na in assets if na.beat_id]
        extra = [na for na in assets if not na.beat_id]
        return beat_keyed, extra, hook

    def _degradable_assets(
        self,
        dispatchers: dict[str, WorkerDispatcher],
        name: str,
        tokens: dict[str, Any] | None,
        beats: list[Beat],
    ) -> tuple[NewAsset, ...]:
        dispatch = dispatchers.get(name)
        if dispatch is None or not beats:
            return ()
        try:
            return dispatch({"brand_kit": tokens, "beats": beats, "guidance": ""}).new_assets
        except Exception as exc:  # degradable: continue with a reduced bundle (ADR 0013)
            log.get().agent_tool_error(name, str(exc))
            return ()

    def _degradable_hook(
        self, dispatchers: dict[str, WorkerDispatcher], tokens: dict[str, Any] | None
    ) -> Hook | None:
        """The text-hook worker is the hook's authority (ADR 0013): its proposal carries the typed
        Hook. Degradable -- on failure there is simply no hook (the run still ships)."""
        dispatch = dispatchers.get("dispatch_text_hook")
        if dispatch is None:
            return None
        try:
            return dispatch({"brand_kit": tokens, "guidance": ""}).hook
        except Exception as exc:  # degradable: no opening hook (ADR 0013)
            log.get().agent_tool_error("dispatch_text_hook", str(exc))
            return None
