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

The Composition JSON is the message contract between the stages. The CLI depends on the service
*interfaces* (the ``*Port`` Protocols below and the existing agent/finalization seams), never their
internals, so the later move to HTTP + a real queue is a transport change rather than a CLI rewrite
(stories 23, 24). Each stage is wrapped so a failure is reported as a legible, stage-named error
with a non-zero exit (story 15).
"""

from __future__ import annotations

import argparse
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
from videogen.agent.vision_advice import VisionAdvisor
from videogen.app.settings import Settings, load_settings
from videogen.kernel.composition import AssetType
from videogen.services.authoring import AuthoredComposition
from videogen.services.finalize import VideoRenderer
from videogen.services.media import ProbeResult, Transcript

# Maps a settings ``authoring_client`` name to its adapter in the ``agent.clients`` package. Adding
# a client is a new entry here plus the module under ``clients/`` -- the rest of the CLI unchanged.
_AUTHORING_CLIENTS = {
    "claude-code": "ClaudeCodeClient",
    "gemini": "GeminiModelClient",
    "anthropic": "AnthropicModelClient",
    "nvidia": "NvidiaModelClient",
    "perplexity": "PerplexityModelClient",
}

# File extensions that mark a b-roll asset as a still image rather than a movie clip; everything
# else is treated as video. The host is always video (its audio is the voiceover, ADR 0005).
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


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
    from videogen import log
    log.get().stage_start(name)
    try:
        yield
        log.get().stage_done(name)
    except PipelineError:
        raise  # already tagged -- don't double-wrap
    except Exception as exc:
        log.get().stage_error(name, exc)
        raise PipelineError(name, exc) from exc


@dataclass
class Pipeline:
    """The in-process wiring of the three services behind their interfaces (ADR 0003).

    Holds the collaborators ``run`` needs and nothing else; the authoring model, the video reviewer,
    and the render adapter are all injected, so swapping a provider or a transport never touches the
    orchestration. ``run`` is the whole command body; ``main`` only parses arguments and calls it.
    """

    media: MediaPort
    authoring: AuthoringPort
    renderer: VideoRenderer
    model_client: ModelClient
    reviewer: ReviewAgent
    advisor: VisionAdvisor | None = None
    max_review_rounds: int = 2
    broll_fetcher: Any = field(default=None)  # PerplexityBrollAgent | None
    broll_fetch_limit: int = 6
    fetched_broll_dir: Path | None = None
    describer: Any = field(default=None)  # GeminiDescribeAgent | None

    def run(self, *, host: str, broll: Sequence[str], brief: str) -> str:
        """Walk the pipeline and return the finished mp4's location.

        Ingest and probe come first so a bad path or unreadable file fails fast, before the
        expensive authoring and render stages (story 8).
        """
        with _stage("ingest"):
            host_id, host_facts, asset_facts = self._ingest(host, broll)
        with _stage("transcribe"):
            transcript = self.media.transcribe(host_id)

        if self.broll_fetcher is not None and self.fetched_broll_dir is not None:
            with _stage("fetch-broll"):
                fetched = self.broll_fetcher.fetch(
                    brief,
                    transcript.text,
                    limit=self.broll_fetch_limit,
                    dest=self.fetched_broll_dir,
                )
                for path in fetched:
                    asset_id = self.media.ingest(str(path))
                    asset_facts.append(
                        _asset_fact(
                            self.media,
                            asset_id,
                            _asset_type(str(path)),
                            self.media.probe(asset_id),
                        )
                    )

        if self.describer is not None:
            with _stage("describe-assets"):
                to_describe = [f for f in asset_facts if f.id != host_id]
                descriptions = self.describer.describe_all(
                    to_describe,
                    brief=brief,
                    transcript=transcript.text,
                )
                asset_facts = [
                    dataclasses.replace(f, description=d.description, usage_advice=d.usage_advice)
                    if (d := descriptions.get(f.id)) is not None else f
                    for f in asset_facts
                ]

        manifest = MediaManifest(
            assets=tuple(asset_facts),
            voiceover=host_id,
            duration=host_facts.duration,
            fps=host_facts.fps,
            transcript=transcript,
        )

        with _stage("author"):
            authored = self.authoring.author(
                manifest,
                brief,
                model_client=self.model_client,
                reviewer=self.reviewer,
                renderer=self.renderer,
                advisor=self.advisor,
                max_review_rounds=self.max_review_rounds,
            )
        with _stage("render"):
            artifact = self.renderer.render_video(
                authored.composition,
                fps=int(manifest.fps),
                duration=manifest.duration,
                name="final.mp4",
            )
        return str(artifact)

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
        facts = [_asset_fact(self.media, host_id, AssetType.video, host_facts)]
        for item in broll:
            asset_id = self.media.ingest(item)
            facts.append(
                _asset_fact(self.media, asset_id, _asset_type(item), self.media.probe(asset_id))
            )
        return host_id, host_facts, facts


def _asset_type(path: str) -> AssetType:
    return AssetType.image if Path(path).suffix.lower() in _IMAGE_SUFFIXES else AssetType.video


def _asset_fact(media: MediaPort, asset_id: str, kind: AssetType, probe: ProbeResult) -> AssetFact:
    """Turn an asset's probe facts into the Manifest's view of it (ADR 0003: facts, no creative
    interpretation). A still image carries no duration, so it is reported as absent."""
    return AssetFact(
        id=asset_id,
        type=kind.value,
        source=str(media.resolve(asset_id)),
        duration=None if kind is AssetType.image else probe.duration,
        width=probe.width or None,
        height=probe.height or None,
    )


def _split_broll(value: str) -> list[str]:
    """Split the comma-separated ``--broll`` value into individual assets, dropping blanks."""
    return [item.strip() for item in value.split(",") if item.strip()]


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
        "--broll", default="", help="Optional comma-separated b-roll assets (clips and/or stills)."
    )
    make.add_argument(
        "--brief", required=True, help="Free-text brief: topic, length, style, must-use moments."
    )
    return parser


def _new_run_dir() -> Path:
    """Create this run's folder under ``renders/``, timestamped so the log inside it correlates."""
    from datetime import datetime

    run_dir = Path("renders") / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def build_default_pipeline(run_dir: Path, settings: Settings | None = None) -> Pipeline:
    """Wire the real services in-process (ADR 0003): MediaService, AuthoringService, and an async
    RenderService behind the render adapter, with the live authoring and review models.

    Every choice that varies between runs -- the authoring client and model, the creation style, the
    reviewer/advisor models, and the review round cap -- comes from ``settings`` (loaded from
    ``settings.json``; see ``app.settings``), so switching any of them is a config edit, not a code
    change. Every render output and agent artifact for this run is persisted under ``run_dir``
    (``renders/<timestamp>/``): the render blob store is rooted there, and AuthoringService writes
    its stills/previews, ``composition.json``, and per-round review feedback there too.

    The model adapters are imported lazily so the CLI module (and its deterministic tests) load
    without the optional provider SDKs; the prerequisites surface only when a real run is launched.
    The default authoring client is Claude Code (ADR 0006) -- it authors through the Claude Code
    CLI's own auth, so a real run needs no API key. Because it is image-blind, it is paired with a
    Gemini ``VisionAdvisor`` (ADR 0007): the loop offers it ``consult_placement`` (render a still,
    ask Gemini, get text advice) as its vision channel; a sighted client ignores the advisor.
    """
    from videogen.agent import creation_styles
    from videogen.agent.gemini_review import GeminiReviewAgent
    from videogen.agent.gemini_vision import GeminiVisionAdvisor
    from videogen.backends.remotion import RemotionBackend
    from videogen.services.authoring import AuthoringService
    from videogen.services.render import RenderService, RenderServiceRenderer
    from videogen.stores.blobs import FilesystemBlobStore

    settings = settings or load_settings()
    backend = RemotionBackend()
    render_service = RenderService(backend=backend, blobs=FilesystemBlobStore(run_dir))
    renderer = RenderServiceRenderer(render_service)
    broll_fetcher = None
    fetched_broll_dir = None
    if settings.broll_fetch:
        from videogen.agent.perplexity_broll import PerplexityBrollAgent

        broll_fetcher = PerplexityBrollAgent()
        fetched_broll_dir = run_dir / "fetched_broll"
    describer = None
    if settings.asset_descriptions:
        from videogen.agent.gemini_describe import GeminiDescribeAgent

        describer = GeminiDescribeAgent(model=settings.describer_model)
    return Pipeline(
        media=_real_media(),
        authoring=AuthoringService(
            backend=backend,
            artifacts_dir=run_dir,
            system=creation_styles.get_style(settings.creation_style),
        ),
        renderer=renderer,
        model_client=_build_authoring_client(settings),
        reviewer=GeminiReviewAgent(model=settings.reviewer_model),
        advisor=GeminiVisionAdvisor(model=settings.advisor_model),
        max_review_rounds=settings.max_review_rounds,
        broll_fetcher=broll_fetcher,
        broll_fetch_limit=settings.broll_fetch_limit,
        fetched_broll_dir=fetched_broll_dir,
        describer=describer,
    )


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


def main(argv: Sequence[str] | None = None, *, pipeline: Pipeline | None = None) -> int:
    """Parse arguments, run the pipeline, print the output path. Returns the process exit code.

    ``pipeline`` is injected by tests; in normal use the real in-process wiring is built on demand.
    """
    from dotenv import load_dotenv

    from videogen import log
    load_dotenv()
    args = _build_parser().parse_args(argv)
    broll = _split_broll(args.broll)
    if pipeline is not None:
        pipe = pipeline  # tests inject a fake pipeline; no run folder or logging side effects
    else:
        run_dir = _new_run_dir()
        log.init(run_dir)
        pipe = build_default_pipeline(run_dir)
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
