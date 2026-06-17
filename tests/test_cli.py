"""End-to-end CLI (Phase 9): argument parsing + in-process orchestration of the three services.

The CLI's own job is parsing and orchestration, so these tests drive it with the three services
replaced by fakes -- no models, no rendering. They assert the externally observable contract: the
stages run in order with the Composition as the message between them, ``--host`` is required,
``--broll`` is split on commas, ``--brief`` is passed through untouched, the final mp4 path is
printed, and a failure at any stage is reported with the stage named and a non-zero exit. The real
authoring/review models and the Remotion render are exercised by the gated E2E smoke, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videogen.agent.perception import Manifest, MediaManifest
from videogen.app.cli import Pipeline, PipelineError, expand_broll_paths, main
from videogen.kernel.builder import Builder
from videogen.kernel.composition import Asset, AssetType, Composition, LayoutName, RegionName
from videogen.services.authoring import AuthoredComposition
from videogen.services.media import ProbeResult, Transcript, Word


def _seeded_composition() -> Composition:
    builder = Builder.new(
        voiceover="host", duration=2.0, assets={"host": Asset(type=AssetType.video, src="host.mp4")}
    )
    builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
    builder.fill_region("s0", RegionName.full, "host")
    return builder.composition


class FakeMedia:
    """Records the calls the CLI makes and returns canned objective facts."""

    def __init__(self, calls: list[str], *, raise_on: str | None = None) -> None:
        self.calls = calls
        self._raise_on = raise_on

    def ingest(self, path: str | Path) -> str:
        self.calls.append(f"ingest:{path}")
        if self._raise_on == "ingest":
            raise OSError("no such file")
        return f"asset-{Path(path).name}"

    def resolve(self, asset_id: str) -> Path:
        return Path("/media") / asset_id

    def probe(self, asset_id: str) -> ProbeResult:
        return ProbeResult(duration=2.0, width=1080, height=1920, fps=30.0)

    def transcribe(self, asset_id: str) -> Transcript:
        self.calls.append(f"transcribe:{asset_id}")
        if self._raise_on == "transcribe":
            raise RuntimeError("whisper exploded")
        return Transcript(words=[Word("hello", 0.1, 0.5), Word("world", 0.6, 1.0)])


class FakeAuthoring:
    """Returns a finished Composition and records the Manifest + brief it was handed."""

    def __init__(self, calls: list[str], *, raise_: bool = False) -> None:
        self.calls = calls
        self._raise = raise_
        self.manifest: Manifest | None = None
        self.brief: str | None = None
        self.composition = _seeded_composition()

    def author(
        self,
        manifest: Manifest,
        brief: str,
        *,
        model_client: object,
        reviewer: object | None = None,
        renderer: object | None = None,
        advisor: object | None = None,
        max_review_rounds: int = 2,
        dispatchers: dict | None = None,
        brand_kit: object | None = None,
        timeline_skeleton: str = "",
    ) -> AuthoredComposition:
        self.calls.append("author")
        self.manifest = manifest
        self.brief = brief
        if self._raise:
            raise RuntimeError("the agent gave up")
        builder = Builder.new(
            voiceover="host",
            duration=2.0,
            assets={"host": Asset(type=AssetType.video, src="host.mp4")},
        )
        builder.add_scene(LayoutName.full, 0.0, 2.0, id="s0")
        builder.fill_region("s0", RegionName.full, "host")
        return AuthoredComposition(
            composition=self.composition,
            report=builder.validate(),
            terminated_clean=True,
            ops_used=2,
            journal=(),
        )


class FakeDescriber:
    """Records describe_all calls; returns empty descriptions."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def describe_all(self, assets, *, brief: str, transcript: str) -> dict:
        self.calls.append(f"describe:{len(assets)}")
        return {}


class FakeRenderer:
    """A VideoRenderer that records the Composition it rendered and writes a marker mp4."""

    def __init__(self, calls: list[str], out: Path, *, raise_: bool = False) -> None:
        self.calls = calls
        self._out = out
        self._raise = raise_
        self.rendered: Composition | None = None

    def render_video(
        self, composition: Composition, *, fps: int, duration: float, name: str | None = None
    ) -> Path:
        self.calls.append("render")
        self.rendered = composition
        if self._raise:
            raise RuntimeError("remotion crashed")
        self._out.write_bytes(b"fake-mp4")
        return self._out


def _pipeline(
    tmp_path: Path,
    *,
    media_raise: str | None = None,
    author_raise: bool = False,
    render_raise: bool = False,
) -> tuple[Pipeline, list[str], FakeAuthoring, FakeRenderer]:
    calls: list[str] = []
    media = FakeMedia(calls, raise_on=media_raise)
    authoring = FakeAuthoring(calls, raise_=author_raise)
    renderer = FakeRenderer(calls, tmp_path / "final.mp4", raise_=render_raise)
    pipeline = Pipeline(
        media=media,
        authoring=authoring,
        renderer=renderer,
        model_client=object(),  # type: ignore[arg-type]
        reviewer=object(),  # type: ignore[arg-type]
    )
    return pipeline, calls, authoring, renderer


def test_run_orchestrates_the_three_services_in_order_with_the_composition_as_the_contract(
    tmp_path: Path,
) -> None:
    pipeline, calls, authoring, renderer = _pipeline(tmp_path)

    out = pipeline.run(host="host.mp4", broll=["clip.mp4"], brief="a 2s short on X")

    # The stages run in the ADR 0003 order: ingest (host + each b-roll) -> transcribe -> author ->
    # render. (Probe/resolve are reads the CLI uses to build the Manifest, not ordered milestones.)
    assert calls == [
        "ingest:host.mp4",
        "ingest:clip.mp4",
        "transcribe:asset-host.mp4",
        "author",
        "render",
    ]
    # The authored Composition is the contract handed straight to the renderer.
    assert renderer.rendered is authoring.composition
    assert out == str(tmp_path / "final.mp4") and Path(out).exists()


def test_run_hands_authoring_a_manifest_built_from_the_media_facts_and_the_untouched_brief(
    tmp_path: Path,
) -> None:
    pipeline, _calls, authoring, _renderer = _pipeline(tmp_path)

    pipeline.run(host="host.mp4", broll=["shot.png", "clip.mp4"], brief="open on the clip")

    manifest = authoring.manifest
    assert isinstance(manifest, MediaManifest)
    assert manifest.voiceover == "asset-host.mp4"  # the host recording is the voiceover (ADR 0005)
    assert manifest.duration == 2.0 and manifest.fps == 30.0
    # The host plus every b-roll asset is declared, with the still typed as an image (no duration).
    kinds = {a.id: a.type for a in manifest.assets}
    assert kinds == {
        "asset-host.mp4": "video",
        "asset-shot.png": "image",
        "asset-clip.mp4": "video",
    }
    shot = next(a for a in manifest.assets if a.id == "asset-shot.png")
    assert shot.duration is None
    assert authoring.brief == "open on the clip"  # passed through untouched (story 21)


def test_main_splits_broll_on_commas_and_passes_the_brief_through(tmp_path: Path) -> None:
    pipeline, _calls, authoring, _renderer = _pipeline(tmp_path)

    code = main(
        ["make", "--host", "h.mp4", "--broll", " a.png , b.mp4 ,", "--brief", "free text"],
        pipeline=pipeline,
    )

    assert code == 0
    assert [a.id for a in authoring.manifest.assets] == [  # type: ignore[union-attr]
        "asset-h.mp4",
        "asset-a.png",
        "asset-b.mp4",
    ]
    assert authoring.brief == "free text"


def test_main_accepts_a_host_only_short_with_no_broll(tmp_path: Path) -> None:
    pipeline, _calls, authoring, _renderer = _pipeline(tmp_path)

    code = main(["make", "--host", "h.mp4", "--brief", "talking head only"], pipeline=pipeline)

    assert code == 0
    assert [a.id for a in authoring.manifest.assets] == ["asset-h.mp4"]  # type: ignore[union-attr]


def test_main_prints_the_output_path_and_closes_the_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline, _calls, _authoring, _renderer = _pipeline(tmp_path)
    closed: list[bool] = []
    pipeline.renderer.close = lambda: closed.append(True)  # type: ignore[attr-defined]

    code = main(["make", "--host", "h.mp4", "--brief", "x"], pipeline=pipeline)

    assert code == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "final.mp4")  # story 14
    assert closed == [True]  # the worker pool is released even on the happy path


def test_main_requires_host() -> None:
    with pytest.raises(SystemExit) as exc:  # argparse exits non-zero on a missing required flag
        main(["make", "--brief", "no host given"])
    assert exc.value.code != 0


def test_expand_broll_folder_one_level_sorted(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "z_last.png").write_bytes(b"x")
    (pack / "a_first.mp4").write_bytes(b"x")
    (pack / "nested").mkdir()
    (pack / "nested" / "hidden.mp4").write_bytes(b"x")
    (pack / "readme.txt").write_bytes(b"skip")

    paths = expand_broll_paths([str(pack)])

    assert paths == [str((pack / "a_first.mp4").resolve()), str((pack / "z_last.png").resolve())]


def test_expand_broll_preserves_comma_order_with_folder(tmp_path: Path) -> None:
    hook = tmp_path / "hook.png"
    hook.write_bytes(b"x")
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "b.mp4").write_bytes(b"x")

    paths = expand_broll_paths([str(hook), str(pack)])

    assert paths[0] == str(hook.resolve())
    assert paths[1] == str((pack / "b.mp4").resolve())


def test_main_authoring_only_requires_broll() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["make", "--authoring-only", "--host", "h.mp4", "--brief", "x"])
    assert exc.value.code == 2


def test_main_authoring_only_requires_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "make",
                "--authoring-only",
                "--host",
                "h.mp4",
                "--broll",
                "a.png",
                "--brief",
                "x",
            ]
        )
    assert exc.value.code == 2


def test_authoring_only_runs_describe_not_ideal_cuts(tmp_path: Path) -> None:
    calls: list[str] = []
    media = FakeMedia(calls)
    authoring = FakeAuthoring(calls)
    renderer = FakeRenderer(calls, tmp_path / "final.mp4")
    describer = FakeDescriber(calls)

    pipeline = Pipeline(
        media=media,
        authoring=authoring,
        renderer=renderer,
        model_client=object(),  # type: ignore[arg-type]
        reviewer=object(),  # type: ignore[arg-type]
        authoring_only=True,
        ideal_cuts_agent=None,
        describer=describer,
    )

    pipeline.run(host="host.mp4", broll=["clip.mp4"], brief="use the b-roll")

    assert "describe:1" in calls
    assert "IdealCuts Plan" not in (authoring.brief or "")
    assert calls == [
        "ingest:host.mp4",
        "ingest:clip.mp4",
        "transcribe:asset-host.mp4",
        "describe:1",
        "author",
        "render",
    ]


@pytest.mark.parametrize(
    ("kwargs", "stage"),
    [
        ({"media_raise": "ingest"}, "ingest"),
        ({"media_raise": "transcribe"}, "transcribe"),
        ({"author_raise": True}, "author"),
        ({"render_raise": True}, "render"),
    ],
)
def test_run_tags_a_failure_with_the_stage_that_broke(
    tmp_path: Path, kwargs: dict[str, object], stage: str
) -> None:
    pipeline, _calls, _authoring, _renderer = _pipeline(tmp_path, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(PipelineError) as exc:
        pipeline.run(host="h.mp4", broll=["b.png"], brief="x")
    assert exc.value.stage == stage


def test_main_reports_the_failing_stage_and_exits_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pipeline, _calls, _authoring, _renderer = _pipeline(tmp_path, author_raise=True)

    code = main(["make", "--host", "h.mp4", "--brief", "x"], pipeline=pipeline)

    assert code == 1  # story 15: a broken stage is diagnosable, not a silent crash
    assert "author" in capsys.readouterr().err
