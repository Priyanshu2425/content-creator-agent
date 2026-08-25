"""End-to-end CLI (Phase 9): `videogen make --host host.mp4 [--broll a.png,b.mp4] --brief "..."`.

This is the single runnable entry point over the whole stack. It is deliberately thin -- argument
parsing plus orchestration only -- so all real logic stays in the services and the kernel (ADR 0003,
story 25). It walks the ADR 0003 + ADR 0005 pipeline with the three services wired as direct
in-process calls behind their interfaces:

    make --host host.mp4 [--broll a.png,b.mp4] --brief "..."
      -> MediaService: ingest + probe + transcribe -> a Media Manifest (objective facts)
      -> AuthoringService: authoring agent builds a validated Composition, then the Phase 8b
         finalization gate renders + video-reviews + corrects it (bounded)
      -> RenderService (via the render adapter): submit_render -> poll -> the finished mp4 path

    make --authoring-only --host host.mp4 --broll ./pack --brief "..."
      -> ingest + transcribe + describe-assets (forced) + author + audio-decider + render
      (skips IdealCuts and GenerateBroll; supplied b-roll required)

The Composition JSON is the message contract between the stages. The CLI depends on the service
*interfaces* (the ``*Port`` Protocols below and the existing agent/finalization seams), never their
internals, so the later move to HTTP + a real queue is a transport change rather than a CLI rewrite
(stories 23, 24). Each stage is wrapped so a failure is reported as a legible, stage-named error
with a non-zero exit (story 15).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from videogen.agent.model import ModelClient
from videogen.agent.perception import AssetFact, Manifest, MediaManifest
from videogen.agent.review import ReviewAgent
from videogen.agent.timeline_skeleton import build_skeleton
from videogen.agent.vision_advice import VisionAdvisor
from videogen.app.settings import Settings, load_settings
from videogen.kernel.composition import Asset, AssetType
from videogen.services.authoring import AuthoredComposition
from videogen.services.finalize import VideoRenderer
from videogen.services.media import ProbeResult, Transcript
from videogen import log, tracing

# Maps a settings ``authoring_client`` name to its adapter in the ``agent.clients`` package. Adding
# a client is a new entry here plus the module under ``clients/`` -- the rest of the CLI unchanged.
_AUTHORING_CLIENTS = {
    "claude-code": "ClaudeCodeClient",
    "gemini": "GeminiModelClient",
    "anthropic": "AnthropicModelClient",
    "nvidia": "NvidiaModelClient",
    "openrouter": "OpenRouterModelClient",
    "perplexity": "PerplexityModelClient",
}

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".m4v", ".mkv"})
_MEDIA_SUFFIXES = _IMAGE_SUFFIXES | _VIDEO_SUFFIXES


class MediaPort(Protocol):
    """The slice of MediaService the CLI orchestrates: facts only (ADR 0003). Structural so a fake
    (or a future HTTP client) satisfies it without the CLI importing a concrete implementation."""

    def ingest(self, path: str | Path) -> str: ...
    def resolve(self, asset_id: str) -> Path: ...
    def probe(self, asset_id: str) -> ProbeResult: ...
    def transcribe(self, asset_id: str) -> Transcript: ...


class AuthoringPort(Protocol):
    """The slice of AuthoringService the CLI calls: Manifest + brief -> a finished Composition,
    finalized through the review gate when a reviewer and renderer are supplied (Phase 8/8b)."""

    def author(
        self,
        manifest: Manifest,
        brief: str,
        *,
        model_client: ModelClient,
        reviewer: ReviewAgent | None = ...,
        renderer: VideoRenderer | None = ...,
        advisor: VisionAdvisor | None = ...,
        max_review_rounds: int = ...,
        dispatchers: dict[str, Any] | None = ...,
        brand_kit: Any = ...,
        timeline_skeleton: str = ...,
    ) -> AuthoredComposition: ...


class PipelineError(RuntimeError):
    """A failure at a named pipeline stage, so the CLI can tell the user which stage broke."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"{stage} failed: {cause}")
        self.stage = stage
        self.cause = cause


@contextmanager
def _stage(name: str) -> Iterator[None]:
    """Tag any failure in this block with the stage it happened in (story 15)."""
    log.get().stage_start(name)
    try:
        with tracing.stage_span(name):
            yield
        log.get().stage_done(name)
    except PipelineError:
        raise  # already tagged -- don't double-wrap
    except Exception as exc:
        log.get().stage_error(name, exc)
        raise PipelineError(name, exc) from exc


@dataclass
class Pipeline:
    """The in-process orchestrator.

    Full pipeline: ingest → transcribe → ideal-cuts → generate-broll → describe-assets? →
    author → audio-decider? → render.

    ``--authoring-only``: ingest → transcribe → describe-assets (forced) → author → …
    """

    media: MediaPort
    authoring: AuthoringPort
    renderer: VideoRenderer
    model_client: ModelClient
    reviewer: ReviewAgent
    advisor: VisionAdvisor | None = None
    max_review_rounds: int = 2
    platform: str = "Instagram"
    authoring_only: bool = False
    ideal_cuts_agent: Any = field(default=None)      # IdealCutsAgent | None
    generate_broll_agent: Any = field(default=None)  # GenerateBrollAgent | None
    generated_broll_dir: Path | None = None
    audio_decider_agent: Any = field(default=None)   # AudioDeciderAgent | None
    describer: Any = field(default=None)             # GeminiDescribeAgent | None
    brand_kit: Any = field(default=None)             # BrandKit | None (the Director's locked design language)
    pipeline: str = "director-loop"                  # "director-loop" (ADR 0008) or "chain" (ADR 0013)
    chain_config: Any = field(default=None)          # ChainConfig | None (per-worker ToT, chain only)
    composer_client: ModelClient | None = None       # the chain Composer's model (ADR 0013: Opus 4.8); falls back to model_client

    def run(self, *, host: str, broll: Sequence[str], brief: str) -> str:
        """Walk the pipeline and return the finished mp4's location."""
        with tracing.pipeline_trace(
            brief=brief,
            platform=self.platform,
            host=host,
        ):
            return self._run(host=host, broll=broll, brief=brief)

    def _run(self, *, host: str, broll: Sequence[str], brief: str) -> str:
        with _stage("ingest"):
            host_id, host_facts, asset_facts = self._ingest(host, broll)
        with _stage("transcribe"):
            transcript = self.media.transcribe(host_id)
            log.get().transcribe_done(len(transcript.words), host_facts.duration)

        manifest = MediaManifest(
            assets=tuple(asset_facts),
            voiceover=host_id,
            duration=host_facts.duration,
            fps=host_facts.fps,
            transcript=transcript,
        )

        # The former IdealCuts stage is folded into the Director (ADR 0008): instead of a separate
        # LLM cut-planner, build the deterministic timeline skeleton (hook window + caption cadence)
        # and hand it to the Director, which authors the cuts itself.
        with _stage("timeline-skeleton"):
            skeleton = build_skeleton(transcript=transcript, duration=host_facts.duration)

        # Resolve the run's brand kit up front: workers (motion graphics) and the author step both
        # receive it, so it must exist before the dispatchers are built.
        run_brand_kit = self.brand_kit
        if run_brand_kit is not None:
            from videogen.agent.brand_kit import FrameMeta

            run_brand_kit = run_brand_kit.with_frame(
                FrameMeta.of(
                    width=int(host_facts.width or 0),
                    height=int(host_facts.height or 0),
                    fps=int(host_facts.fps),
                )
            )

        # B-roll generation is now an in-loop worker the Director dispatches on demand (ADR 0008),
        # not a fixed upstream stage. Build the dispatcher here (it binds media ingest + the worker
        # agent) and hand it to the author step; the Director decides whether and when to call it.
        dispatchers: dict[str, Any] = {}
        if (
            not self.authoring_only
            and self.generate_broll_agent is not None
            and self.generated_broll_dir is not None
        ):
            dispatchers["dispatch_broll"] = _make_broll_dispatcher(
                media=self.media,
                agent=self.generate_broll_agent,
                manifest=manifest,
                brief=brief,
                platform=self.platform,
                ideal_cuts_plan="",
                dest=self.generated_broll_dir,
            )

        # The text-hook worker needs only the transcript + a model, so it is always available.
        dispatchers["dispatch_text_hook"] = _make_text_hook_dispatcher(
            model_client=self.model_client, transcript_text=transcript.text
        )

        # The creative direction worker needs only the brief + transcript + a model.
        dispatchers["dispatch_creative_direction"] = _make_creative_direction_dispatcher(
            brief=brief,
            transcript_text=transcript.text,
        )

        # Motion graphics — always available; uses same Remotion backend as stat viz.
        if not self.authoring_only and self.generated_broll_dir is not None:
            dispatchers["dispatch_motion_graphics"] = _make_motion_graphics_dispatcher(
                media=self.media,
                model_client=self.model_client,
                manifest=manifest,
                brief=brief,
                transcript_text=transcript.text,
                dest=self.generated_broll_dir,
                brand_kit=run_brand_kit,
            )

        if self.authoring_only or self.describer is not None:
            if self.describer is None:
                raise RuntimeError("describe-assets required but no describer is configured")
            with _stage("describe-assets"):
                asset_facts = _describe_assets(
                    self.describer,
                    host_id=host_id,
                    asset_facts=asset_facts,
                    brief=brief,
                    transcript=transcript.text,
                )
                manifest = MediaManifest(
                    assets=tuple(asset_facts),
                    voiceover=host_id,
                    duration=host_facts.duration,
                    fps=host_facts.fps,
                    transcript=transcript,
                )

        if self.pipeline == "chain":
            composition = self._author_chain(
                manifest=manifest,
                brief=brief,
                dispatchers=dispatchers,
                brand_kit=run_brand_kit,
            )
        else:
            with _stage("author"):
                authored = self.authoring.author(
                    manifest,
                    brief,
                    model_client=self.model_client,
                    reviewer=self.reviewer,
                    renderer=self.renderer,
                    advisor=self.advisor,
                    max_review_rounds=self.max_review_rounds,
                    dispatchers=dispatchers or None,
                    brand_kit=run_brand_kit,
                    timeline_skeleton=skeleton.summary(),
                )
            composition = authored.composition
        if self.audio_decider_agent is not None:
            with _stage("audio-decider"):
                composition = self.audio_decider_agent.annotate(composition)

        with _stage("render"):
            artifact = self.renderer.render_video(
                composition,
                fps=int(manifest.fps),
                duration=manifest.duration,
                name="final.mp4",
            )
        tracing.update_pipeline_output(str(artifact))
        return str(artifact)

    def _author_chain(
        self,
        *,
        manifest: MediaManifest,
        brief: str,
        dispatchers: dict[str, Any],
        brand_kit: Any,
    ) -> Any:
        """Author via the chain pipeline (ADR 0013): fixed-order workers + the Composer, reusing the
        same dispatchers the director loop pulls. A fatal chain stage surfaces as a stage-named
        ``PipelineError`` (creative-direction / compose); degradable stages continue internally."""
        from videogen.agent.chain.config import ChainConfig
        from videogen.agent.chain.strategy import ChainStageError, ChainStrategy

        tokens = None
        if brand_kit is not None:
            getter = getattr(brand_kit, "tokens", None)
            tokens = getter() if callable(getter) else None

        # The Composer runs on its own dedicated client (ADR 0013: Opus 4.8 via Claude Code), not the
        # authoring client the workers/loop use; falls back to the authoring client if none was wired.
        strategy = ChainStrategy(
            model_client=self.composer_client or self.model_client,
            config=self.chain_config or ChainConfig(),
        )
        log.get().stage_start("chain-author")
        try:
            with tracing.stage_span("chain-author"):
                composition = strategy.author(
                    manifest=manifest,
                    brief=brief,
                    dispatchers=dispatchers,
                    brand_kit_tokens=tokens,
                )
            log.get().stage_done("chain-author")
            return composition
        except ChainStageError as exc:
            log.get().stage_error(exc.stage, exc.cause)
            raise PipelineError(exc.stage, exc.cause) from exc
        except Exception as exc:
            log.get().stage_error("chain-author", exc)
            raise PipelineError("chain-author", exc) from exc

    def close(self) -> None:
        """Release any resources the collaborators hold (the render worker pool)."""
        closer = getattr(self.renderer, "close", None)
        if callable(closer):
            closer()

    def _ingest(
        self, host: str, broll: Sequence[str]
    ) -> tuple[str, ProbeResult, list[AssetFact]]:
        host_id = self.media.ingest(host)
        host_facts = self.media.probe(host_id)
        log.get().ingest_asset(
            host_id, "video", host_facts.duration, host_facts.width, host_facts.height
        )
        facts = [_asset_fact(self.media, host_id, AssetType.video, host_facts)]
        for item in broll:
            asset_id = self.media.ingest(item)
            kind = _asset_type(item)
            probe = self.media.probe(asset_id)
            log.get().ingest_asset(
                asset_id,
                kind.value,
                None if kind is AssetType.image else probe.duration,
                probe.width,
                probe.height,
            )
            facts.append(_asset_fact(self.media, asset_id, kind, probe))
        return host_id, host_facts, facts


def _is_media_file(path: Path) -> bool:
    return path.suffix.lower() in _MEDIA_SUFFIXES


def _asset_type(path: str) -> AssetType:
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return AssetType.image
    if suffix in _VIDEO_SUFFIXES:
        return AssetType.video
    raise ValueError(f"unsupported media extension for b-roll: {path!r}")


def _asset_fact(
    media: MediaPort,
    asset_id: str,
    kind: AssetType,
    probe: ProbeResult,
    *,
    description: str | None = None,
    usage_advice: str | None = None,
) -> AssetFact:
    """Turn an asset's probe facts into the Manifest's view of it (ADR 0003: facts, no creative
    interpretation). A still image carries no duration, so it is reported as absent."""
    return AssetFact(
        id=asset_id,
        type=kind.value,
        source=str(media.resolve(asset_id)),
        duration=None if kind is AssetType.image else probe.duration,
        width=probe.width or None,
        height=probe.height or None,
        description=description,
        usage_advice=usage_advice,
    )


def _make_broll_dispatcher(
    *,
    media: MediaPort,
    agent: Any,
    manifest: MediaManifest,
    brief: str,
    platform: str,
    ideal_cuts_plan: str,
    dest: Path,
) -> Any:
    """Build the b-roll worker dispatcher (ADR 0008).

    When the Director calls ``dispatch_broll``, this runs the b-roll worker (which generates stills +
    stat-viz clips to ``dest``), ingests each produced file as a fact, and returns a proposal naming
    the new assets. The loop registers them into the Builder so the Director can place them — the
    worker never composites.
    """
    from videogen.agent.dispatch import NewAsset, WorkerProposal

    def dispatch(guidance: dict[str, Any]) -> WorkerProposal:
        scratchpad = str(guidance.get("scratchpad", ""))
        log.get().agent_dispatch_input("dispatch_broll", inputs={
            "brief": brief,
            "platform": platform,
            "ideal_cuts_plan": ideal_cuts_plan,
            "transcript": manifest.transcript.text,
            "brand_kit": guidance.get("brand_kit"),
            "creative_direction_scratchpad": scratchpad,
            "director_guidance": str(guidance.get("guidance", "")),
        })
        generated = agent.run(
            manifest, brief, platform, ideal_cuts_plan, dest=dest,
            brand_kit_tokens=guidance.get("brand_kit"),  # type: ignore[arg-type]
            creative_direction=scratchpad,
            director_guidance=str(guidance.get("guidance", "")),
            beats=guidance.get("beats", ()),  # type: ignore[arg-type]
        )
        new_assets: list[NewAsset] = []
        lines: list[str] = []
        for slot in generated.slots:
            asset_id = media.ingest(str(slot.path))
            kind = _asset_type(str(slot.path))
            asset = Asset(type=AssetType(kind.value), src=str(media.resolve(asset_id)))
            new_assets.append(
                NewAsset(asset_id=asset_id, asset=asset, description=slot.prompt, beat_id=slot.beat_id)
            )
            beat_note = f" [beat {slot.beat_id}]" if slot.beat_id else ""
            lines.append(f"- {asset_id} ({kind.value}){beat_note}: {slot.prompt}")
        text = (
            "B-roll worker produced these assets (styled to the brand kit):\n" + "\n".join(lines)
            if lines
            else "B-roll worker produced no usable assets for this video."
        )
        return WorkerProposal(proposal_text=text, new_assets=tuple(new_assets))

    return dispatch


def _make_text_hook_dispatcher(*, model_client: ModelClient, transcript_text: str) -> Any:
    """Build the text-hook worker dispatcher (ADR 0008).

    When the Director calls ``dispatch_text_hook``, this runs the TextHookAgent over the transcript
    and returns its ranked candidates as a proposal. It produces no assets -- the Director picks one
    and places it with ``add_title``.
    """
    import os

    from videogen.agent.dispatch import WorkerProposal

    # tot_enabled routing (ADR 0011): the deliberating ToT variant runs only when explicitly
    # enabled, and only on Gemini (it builds its own hot/cold clients). Default is the legacy worker.
    if os.getenv("VIDEOGEN_TOT_TEXT_HOOK", "").lower() in {"1", "true", "yes", "on"}:
        from videogen.agent.text_hook_tot import TextHookToTAgent

        agent: Any = TextHookToTAgent()
    else:
        from videogen.agent.text_hook import TextHookAgent

        agent = TextHookAgent(model_client)

    def dispatch(guidance: dict[str, Any]) -> WorkerProposal:
        log.get().agent_dispatch_input("dispatch_text_hook", inputs={
            "transcript": transcript_text,
            "audience": str(guidance.get("guidance", "")),
            "brand_kit": guidance.get("brand_kit"),
        })
        proposal = agent.generate(
            transcript=transcript_text,
            audience=str(guidance.get("guidance", "")),
            brand_kit=guidance.get("brand_kit"),
        )
        # The text-hook worker is the hook's authority (ADR 0013): its chosen line becomes the typed
        # ``composition.hook``. The look defaults from the brand kit (box = accent); the chain writes
        # the hook to the composition deterministically -- the Composer never places it.
        from videogen.kernel.composition import Hook

        chosen = proposal.recommended_text() if hasattr(proposal, "recommended_text") else ""
        bk = guidance.get("brand_kit") or {}
        accent = (bk.get("colors") or {}).get("accent") if isinstance(bk, dict) else None
        hook = Hook(text=chosen, box_color=accent, brand="buildspace labs") if chosen else None
        return WorkerProposal(proposal_text=proposal.to_text(), new_assets=(), hook=hook)

    return dispatch


def _flag_on(name: str, *, default: bool) -> bool:
    """Read a truthy env flag, defaulting to ``default`` when unset (ADR 0011/0012 rollout flags)."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _make_creative_direction_dispatcher(
    *, brief: str, transcript_text: str
) -> Any:
    """Build the creative direction worker dispatcher (ADR 0008/0012).

    When the Director calls ``dispatch_creative_direction``, this runs the CreativeDirectionAgent over
    the brief + transcript (plus the Director's scratchpad context and brand-kit tokens). Under
    ``VIDEOGEN_BEAT_PLAN_ENABLED`` (default **on**, ADR 0012) the worker returns a typed ``BeatPlan``
    the loop executes into placements; with the flag off it falls back to the legacy prose proposal.

    Always uses Gemini (vision-capable) so brand-kit reference images are visible.
    """
    import os

    from videogen.agent.dispatch import WorkerProposal
    from videogen.agent.clients.gemini import GeminiModelClient

    tot = os.getenv("VIDEOGEN_TOT_CREATIVE_DIRECTION", "").lower() in {"1", "true", "yes", "on"}
    beat_plan_on = _flag_on("VIDEOGEN_BEAT_PLAN_ENABLED", default=True)

    # tot_enabled routing (ADR 0011): the deliberating ToT variant runs only when explicitly enabled.
    # It still emits prose (typed BeatPlan output for ToT is a later slice), so the beat-plan path is
    # the single-pass agent only.
    if tot:
        from videogen.agent.creative_direction_tot import CreativeDirectionToTAgent

        agent: Any = CreativeDirectionToTAgent()
    else:
        from videogen.agent.creative_direction import CreativeDirectionAgent

        agent = CreativeDirectionAgent(GeminiModelClient(model="gemini-2.5-flash"))

    def dispatch(guidance: dict[str, Any]) -> WorkerProposal:
        log.get().agent_dispatch_input("dispatch_creative_direction", inputs={
            "brief": brief,
            "transcript": transcript_text,
            "brand_kit": guidance.get("brand_kit"),
            "scratchpad": str(guidance.get("scratchpad", "")),
            "guidance": str(guidance.get("guidance", "")),
            "beat_plan_enabled": beat_plan_on and not tot,
        })
        kwargs = dict(
            brief=brief,
            transcript=transcript_text,
            brand_kit=guidance.get("brand_kit"),
            scratchpad=str(guidance.get("scratchpad", "")),
            guidance=str(guidance.get("guidance", "")),
        )
        if beat_plan_on and not tot:
            beat_plan = agent.generate(**kwargs)  # type: ignore[arg-type]
            return WorkerProposal(
                proposal_text=_summarize_beat_plan(beat_plan),
                new_assets=(),
                beat_plan=beat_plan,
            )
        # Legacy prose fallback: ToT (still prose) or beat_plan disabled.
        prose = agent.generate_prose(**kwargs) if not tot else agent.generate(**kwargs)  # type: ignore[arg-type]
        return WorkerProposal(proposal_text=prose, new_assets=())

    return dispatch


def _summarize_beat_plan(beat_plan: Any) -> str:
    """A human-readable digest of the BeatPlan for the shared scratchpad (the Director also receives
    the typed plan, which it executes deterministically)."""
    lines = ["Creative direction (BeatPlan):"]
    for b in beat_plan.beats:
        lines.append(
            f"- [{b.id}] {b.role} (words {b.transcript_span[0]}-{b.transcript_span[1]}, "
            f"{b.asset_spec.kind}): {b.intent}"
        )
    return "\n".join(lines)


def _make_motion_graphics_dispatcher(
    *,
    media: MediaPort,
    model_client: ModelClient,
    manifest: MediaManifest,
    brief: str,
    transcript_text: str,
    dest: Path,
    brand_kit: Any | None,
) -> Any:
    """Build the motion-graphics worker dispatcher (ADR 0008).

    When the Director calls ``dispatch_motion_graphics``, this runs the MotionGraphicsAgent
    to produce animated text clips (title cards, lower-thirds, CTA, kinetic text) via Remotion.
    Each clip is ingested as an asset and returned as a new-asset proposal, just like b-roll.
    """
    from videogen.agent.dispatch import NewAsset, WorkerProposal
    from videogen.agent.motion_graphics import MotionGraphicsAgent
    from videogen.agent.clients.gemini import GeminiModelClient
    from videogen.agent.creative_direction import _IMAGE_SUFFIXES as _MG_IMG_SUFFIXES, _BRAND_KIT_DIR as _MG_BK_DIR

    bk_imgs: tuple[bytes, ...] = ()
    if _MG_BK_DIR.exists():
        bk_imgs = tuple(
            f.read_bytes() for f in sorted(_MG_BK_DIR.iterdir())
            if f.suffix.lower() in _MG_IMG_SUFFIXES
        )

    agent = MotionGraphicsAgent(GeminiModelClient(model="gemini-2.5-flash"))

    def dispatch(guidance: dict[str, Any]) -> WorkerProposal:
        scratchpad = str(guidance.get("scratchpad", ""))
        log.get().agent_dispatch_input("dispatch_motion_graphics", inputs={
            "brief": brief,
            "transcript": transcript_text,
            "creative_direction_scratchpad": scratchpad,
            "director_guidance": str(guidance.get("guidance", "")),
            "brand_kit": guidance.get("brand_kit"),
            "brand_kit_images": f"{len(bk_imgs)} image(s)",
            "fps": int(manifest.fps),
        })
        result = agent.run(
            brief=brief,
            transcript=transcript_text,
            creative_direction=scratchpad,
            director_guidance=str(guidance.get("guidance", "")),
            brand_kit=guidance.get("brand_kit"),  # type: ignore[arg-type]
            brand_kit_images=bk_imgs,
            dest=dest,
            fps=int(manifest.fps),
        )
        new_assets: list[NewAsset] = []
        lines: list[str] = []
        for slot in result.slots:
            asset_id = media.ingest(str(slot.path))
            kind = _asset_type(str(slot.path))
            asset = Asset(type=AssetType(kind.value), src=str(media.resolve(asset_id)))
            new_assets.append(NewAsset(asset_id=asset_id, asset=asset, description=slot.label))
            lines.append(f"- {asset_id} ({slot.duration_s}s): {slot.label}")
        text = (
            "Motion Graphics Agent produced these animated clips (brand-kit styled):\n" + "\n".join(lines)
            if lines
            else "Motion Graphics Agent produced no clips."
        )
        return WorkerProposal(proposal_text=text, new_assets=tuple(new_assets))

    return dispatch


def _describe_assets(
    describer: Any,
    *,
    host_id: str,
    asset_facts: list[AssetFact],
    brief: str,
    transcript: str,
) -> list[AssetFact]:
    """Vision-describe every b-roll asset (not the host) for the authoring perception packet."""
    to_describe = [f for f in asset_facts if f.id != host_id]
    if not to_describe:
        log.get().describe_done(0)
        return asset_facts
    descriptions = describer.describe_all(
        to_describe,
        brief=brief,
        transcript=transcript,
    )
    return [
        dataclasses.replace(f, description=d.description, usage_advice=d.usage_advice)
        if (d := descriptions.get(f.id)) is not None
        else f
        for f in asset_facts
    ]


def _split_broll(value: str) -> list[str]:
    """Split the comma-separated ``--broll`` value into paths, dropping blanks."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _expand_broll_entry(entry: str) -> list[str]:
    """Expand one ``--broll`` token (file or one-level folder) into ingestible media paths."""
    path = Path(entry).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"b-roll path does not exist: {entry}")
    if path.is_file():
        if not _is_media_file(path):
            log.get().broll_path_skipped(str(path), "unsupported extension")
            return []
        return [str(path.resolve())]
    if path.is_dir():
        resolved: list[str] = []
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_file():
                continue
            if _is_media_file(child):
                resolved.append(str(child.resolve()))
            else:
                log.get().broll_path_skipped(str(child), "unsupported extension")
        return resolved
    raise ValueError(f"b-roll path is neither a file nor a directory: {entry}")


def expand_broll_paths(entries: Sequence[str]) -> list[str]:
    """Expand comma-list order: each entry is a file or a folder (immediate children only)."""
    expanded: list[str] = []
    for entry in entries:
        expanded.extend(_expand_broll_entry(entry))
    log.get().broll_expand_done(len(expanded))
    return expanded


def _has_gemini_api_key() -> bool:
    # True for either auth path: ADC/Vertex (GOOGLE_GENAI_USE_VERTEXAI) or an API key.
    from videogen.genai_client import have_gemini_credentials

    return have_gemini_credentials()


def _prepare_broll_for_make(*, broll_arg: str, authoring_only: bool) -> list[str]:
    """Parse and expand ``--broll``; enforce authoring-only contracts."""
    entries = _split_broll(broll_arg)
    if authoring_only:
        if not entries:
            _cli_error(
                "--authoring-only requires --broll "
                "(comma-separated media files and/or a folder of b-roll)."
            )
        if not _has_gemini_api_key():
            _cli_error(
                "--authoring-only requires Gemini for asset descriptions; "
                "authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or set GOOGLE_API_KEY/GEMINI_API_KEY."
            )
    if not entries:
        return []
    try:
        paths = expand_broll_paths(entries)
    except (FileNotFoundError, ValueError) as exc:
        _cli_error(str(exc))
    if authoring_only and not paths:
        _cli_error(
            "--authoring-only found no ingestible b-roll under --broll "
            "(expected image/video files or a folder whose immediate children are media)."
        )
    return paths


def _cli_error(message: str) -> None:
    print(f"videogen: {message}", file=sys.stderr)
    raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videogen", description="Talking-head-first short-form video generator."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make", help="Turn a host recording + brief into a finished short.")
    make.add_argument(
        "--host", required=True, help="Host-cam recording; its audio is the voiceover master clock."
    )
    make.add_argument(
        "--broll",
        default="",
        help=(
            "Comma-separated b-roll files and/or folders. A folder ingests media files "
            "among its immediate children only (not subfolders)."
        ),
    )
    make.add_argument(
        "--brief", required=True, help="Free-text brief: topic, length, style, must-use moments."
    )
    make.add_argument(
        "--brand-profile",
        default="",
        help=(
            "Optional path to a brand profile JSON (colors, font, caption_style, safe_zones, "
            "sfx). The Director locks it as the brand kit; omitted means a default kit is derived."
        ),
    )
    make.add_argument(
        "--authoring-only",
        action="store_true",
        help=(
            "Supplied-b-roll mode: skip IdealCuts and Kling generation; require --broll; "
            "force Gemini asset descriptions before authoring."
        ),
    )
    make.add_argument(
        "--pipeline",
        choices=("director-loop", "chain"),
        default="director-loop",
        help=(
            "Authoring topology (ADR 0013). 'director-loop' (default): the Director pulls workers on "
            "demand and authors op-by-op. 'chain': fixed-order workers + a single Composer that emits "
            "the Composition directly."
        ),
    )
    make.add_argument(
        "--tot",
        action="store_true",
        help=(
            "Use the Tree-of-Thoughts deliberating worker variants (ADR 0011) for creative direction "
            "and text hook. Gemini-only; errors if Gemini is not wired. Works on both pipelines."
        ),
    )
    make.add_argument(
        "--hook",
        action="store_true",
        help=(
            "Chain pipeline only: enable the opening text-hook (the text-hook worker + the animated "
            "hook card). Disabled by default -- pass --hook to turn it on."
        ),
    )

    preview = sub.add_parser(
        "preview",
        help="Open a finished run in the browser (Remotion Studio) from its persisted IR.",
    )
    preview.add_argument(
        "run",
        help=(
            "A run directory (e.g. renders/2026-06-21T19-18-33) or a path to a *.ir.json file. "
            "Stages the run's assets and opens the Main composition in Remotion Studio."
        ),
    )
    return parser


def _load_brand_profile(path: str) -> dict[str, Any] | None:
    """Load a brand profile JSON from ``--brand-profile`` (empty string → no profile)."""
    if not path:
        return None
    import json

    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        _cli_error(f"--brand-profile must be a JSON object, got {type(data).__name__}")
    return data


def _new_run_dir() -> Path:
    """Create this run's folder under ``renders/``, timestamped so the log inside it correlates."""
    from datetime import datetime

    run_dir = Path("renders") / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def build_default_pipeline(
    run_dir: Path,
    settings: Settings | None = None,
    *,
    authoring_only: bool = False,
    brand_profile: dict[str, Any] | None = None,
    pipeline: str = "director-loop",
    chain_config: Any = None,
) -> Pipeline:
    """Wire the real services in-process (ADR 0003): MediaService, AuthoringService, and an async
    RenderService behind the render adapter, with the live authoring and review models.

    When ``authoring_only`` is true, IdealCuts and GenerateBroll are omitted and the Gemini
    describer is always wired (requires API keys in the environment).
    """
    from videogen.agent.gemini_vision import GeminiVisionAdvisor
    from videogen.backends.remotion import RemotionBackend
    from videogen.services.authoring import AuthoringService
    from videogen.services.render import RenderService, RenderServiceRenderer
    from videogen.stores.blobs import FilesystemBlobStore

    from videogen.agent.sfx import SFXAgent

    settings = settings or load_settings()
    # The Director's locked design language (ADR 0008). Built from the optional brand profile, else
    # sensible defaults. v1 derivation ignores the brief (deterministic); frame meta fills in at run
    # time. Its StyleBrief projection styles the stat-viz clips, superseding DEFAULT_STYLE_BRIEF.
    from videogen.agent.brand_kit import build_brand_kit

    brand_kit = build_brand_kit(profile=brand_profile)
    backend = RemotionBackend()
    render_service = RenderService(backend=backend, blobs=FilesystemBlobStore(run_dir))
    renderer = RenderServiceRenderer(render_service)
    model_client = _build_authoring_client(settings)

    # The chain pipeline's Composer runs on its own model (ADR 0013: Opus 4.8 via the Claude Code
    # SDK), independent of the authoring client the workers use. Built only for the chain.
    composer_client: ModelClient | None = None
    if pipeline == "chain":
        from videogen.agent.clients.claude_code import ClaudeCodeClient

        composer_client = ClaudeCodeClient(model=settings.composer_model)

    ideal_cuts_agent = None
    generate_broll_agent = None
    generated_broll_dir = None
    describer = None

    if authoring_only:
        from videogen.agent.gemini_describe import GeminiDescribeAgent

        describer = GeminiDescribeAgent(model=settings.describer_model)
    else:
        from videogen.agent.generate_broll import GenerateBrollAgent
        from videogen.agent.stat_viz import StatVizRenderer
        from videogen.creation.nano_banana import NanoBananaCreator

        from videogen.agent.creative_direction import _IMAGE_SUFFIXES, _BRAND_KIT_DIR
        bk_images: tuple[bytes, ...] = ()
        if _BRAND_KIT_DIR.exists():
            bk_images = tuple(
                f.read_bytes()
                for f in sorted(_BRAND_KIT_DIR.iterdir())
                if f.suffix.lower() in _IMAGE_SUFFIXES
            )
        creator = NanoBananaCreator(model=settings.broll_image_model, reference_images=bk_images)
        # IdealCuts is folded into the Director (ADR 0008); no standalone cut-planner is wired.
        generate_broll_agent = GenerateBrollAgent(
            model_client,
            creator,
            stat_viz_renderer=StatVizRenderer(),
            style_brief=brand_kit.to_style_brief(),
        )
        generated_broll_dir = run_dir / "generated_broll"
        if settings.asset_descriptions:
            from videogen.agent.gemini_describe import GeminiDescribeAgent

            describer = GeminiDescribeAgent(model=settings.describer_model)

    return Pipeline(
        media=_real_media(),
        authoring=AuthoringService(
            backend=backend,
            artifacts_dir=run_dir,
        ),
        renderer=renderer,
        model_client=model_client,
        reviewer=_build_reviewer(settings),
        advisor=GeminiVisionAdvisor(model=settings.advisor_model),
        max_review_rounds=settings.max_review_rounds,
        platform=settings.platform,
        authoring_only=authoring_only,
        ideal_cuts_agent=ideal_cuts_agent,
        generate_broll_agent=generate_broll_agent,
        generated_broll_dir=generated_broll_dir,
        audio_decider_agent=SFXAgent(),  # the single SFX authority (ADR 0009), deterministic
        describer=describer,
        brand_kit=brand_kit,
        pipeline=pipeline,
        chain_config=chain_config,
        composer_client=composer_client,
    )


def _build_reviewer(settings: Settings) -> ReviewAgent:
    """Pick the finalization reviewer (story 14): the Claude-Code JSON reviewer by default, or the
    Gemini full-motion reviewer when ``review_client = "gemini"``. Both implement ReviewAgent; Gemini
    is kept available, only the default changes."""
    if settings.review_client == "gemini":
        from videogen.agent.gemini_review import GeminiReviewAgent

        return GeminiReviewAgent(model=settings.reviewer_model)
    from videogen.agent.claude_review import ClaudeReviewAgent

    return ClaudeReviewAgent(model="claude-opus-4-8")


def _build_authoring_client(settings: Settings) -> ModelClient:
    """Construct the authoring ModelClient named by ``settings.authoring_client`` (with its model).

    ``authoring_model = null`` keeps the client's own default model. Lazy import keeps the provider
    SDKs off the CLI's import path until a real run picks a client."""
    from videogen.agent import clients
    attr = _AUTHORING_CLIENTS.get(settings.authoring_client)
    if attr is None:
        known = ", ".join(sorted(_AUTHORING_CLIENTS))
        raise RuntimeError(
            f"unknown authoring_client {settings.authoring_client!r} in settings.json; "
            f"known: {known}"
        )
    cls = getattr(clients, attr)
    client: ModelClient = cls(model=settings.authoring_model) if settings.authoring_model else cls()
    return client


def _real_media() -> MediaPort:
    from videogen.services.media import MediaService

    return MediaService()


def _configure_tot(*, tot: bool, pipeline_name: str, hook: bool = False) -> Any:
    """Apply ``--tot``/``--hook`` and return the ChainConfig record (ADR 0011/0013).

    ToT worker variants are selected via env flags the dispatchers read. ToT is **Gemini-only**, so
    ``--tot`` without Gemini errors clearly rather than silently falling back to single-pass. In the
    chain, creative direction stays on its BeatPlan path (a CD-ToT that emits a BeatPlan is a later
    slice), so ``--tot`` there flips the text-hook worker only; the director-loop flips both.

    ``hook`` (``--hook``) enables the opening text-hook in the chain; it is disabled by default, so
    the text-hook worker is not dispatched and no hook card is rendered unless turned on.
    """
    from videogen.agent.chain.config import ChainConfig

    if pipeline_name == "chain":
        os.environ["VIDEOGEN_BEAT_PLAN_ENABLED"] = "1"  # the chain's contract: BeatPlan forced on
    if not tot:
        return ChainConfig(hook_enabled=hook)
    if not _has_gemini_api_key():
        _cli_error(
            "--tot uses the Tree-of-Thoughts workers, which are Gemini-only; authenticate via ADC "
            "(GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or set GOOGLE_API_KEY/GEMINI_API_KEY."
        )
    os.environ["VIDEOGEN_TOT_TEXT_HOOK"] = "1"
    cd_tot = pipeline_name != "chain"
    if cd_tot:
        os.environ["VIDEOGEN_TOT_CREATIVE_DIRECTION"] = "1"
    return ChainConfig(creative_direction_tot=cd_tot, text_hook_tot=True, hook_enabled=hook)


def main(argv: Sequence[str] | None = None, *, pipeline: Pipeline | None = None) -> int:
    """Parse arguments, run the pipeline, print the output path. Returns the process exit code.

    ``pipeline`` is injected by tests; in normal use the real in-process wiring is built on demand.
    """
    from dotenv import load_dotenv

    from videogen import log

    load_dotenv()
    args = _build_parser().parse_args(argv)

    if args.command == "preview":
        from videogen.app.preview import run_preview

        try:
            return run_preview(args.run)
        except FileNotFoundError as exc:
            _cli_error(str(exc))

    authoring_only = bool(getattr(args, "authoring_only", False))
    pipeline_name = getattr(args, "pipeline", "director-loop")
    chain_config = _configure_tot(
        tot=bool(getattr(args, "tot", False)),
        pipeline_name=pipeline_name,
        hook=bool(getattr(args, "hook", False)),
    )

    if pipeline is not None:
        # Injected test pipelines use FakeMedia and do not require on-disk b-roll paths.
        entries = _split_broll(args.broll)
        if authoring_only:
            if not entries:
                _cli_error(
                    "--authoring-only requires --broll "
                    "(comma-separated media files and/or a folder of b-roll)."
                )
            if not _has_gemini_api_key():
                _cli_error(
                    "--authoring-only requires Gemini for asset descriptions; "
                    "authenticate via ADC (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT) or set GOOGLE_API_KEY/GEMINI_API_KEY."
                )
        broll = entries
        pipe = pipeline
    else:
        broll = _prepare_broll_for_make(broll_arg=args.broll, authoring_only=authoring_only)
        run_dir = _new_run_dir()
        log.init(run_dir)
        log.get().pipeline_mode(authoring_only=authoring_only)
        pipe = build_default_pipeline(
            run_dir,
            authoring_only=authoring_only,
            brand_profile=_load_brand_profile(args.brand_profile),
            pipeline=pipeline_name,
            chain_config=chain_config,
        )
    try:
        out = pipe.run(host=args.host, broll=broll, brief=args.brief)
    except PipelineError as exc:
        log.get().pipeline_error(exc.stage, exc.cause)
        print(f"videogen: {exc}", file=sys.stderr)
        return 1
    finally:
        pipe.close()
    log.get().pipeline_done(out)
    print(out)
    return 0
