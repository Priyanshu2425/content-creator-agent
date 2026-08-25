"""ChainStrategy: fixed-order orchestration + per-stage failure policy (ADR 0013, slices 02/04/05/06/09).

Workers are faked at the dispatcher seam and the Composer is stubbed, so these tests assert the
*topology and policy*: creative direction is fatal, generators/hook are degradable, an all-None bundle
still composes, and the Composer receives a typed bundle (no prose scratchpad).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from videogen.agent.beat_plan import AssetSpec, Beat, BeatPlan
from videogen.agent.chain.composer import ComposerError
from videogen.agent.chain.config import ChainConfig
from videogen.agent.chain.strategy import ChainStageError, ChainStrategy
from videogen.agent.dispatch import NewAsset, WorkerProposal
from videogen.kernel.composition import Asset, AssetType, Audio, Composition, Hook


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


@dataclass(frozen=True)
class _Manifest:
    voiceover: str = "host"
    duration: float = 2.0
    fps: float = 30.0
    assets: tuple = ()
    transcript: _Transcript = field(
        default_factory=lambda: _Transcript(
            [_Word("a", 0.0, 1.0), _Word("b", 1.0, 2.0)]
        )
    )


PLAN = BeatPlan(
    beats=(
        Beat(id="b1", transcript_span=(0, 1), role="climax", intent="payoff",
             asset_spec=AssetSpec(kind="broll-image")),
    )
)


def _broll_asset() -> NewAsset:
    return NewAsset(asset_id="asset_b1", asset=Asset(type=AssetType.image, src="b1.png"),
                    beat_id="b1")


@dataclass
class StubComposer:
    """Captures the bundle it was handed and returns a fixed Composition (or raises)."""

    raise_error: bool = False
    seen: dict = field(default_factory=dict)

    def compose(self, *, manifest, brief, resolved_beats, brand_kit_tokens, extra_assets):
        self.seen = {"resolved": resolved_beats, "extra": extra_assets}
        if self.raise_error:
            raise ComposerError("boom")
        return Composition(
            assets={"host": Asset(type=AssetType.video, src="host.mp4")},
            voiceover=Audio(asset="host"),
        )


def _dispatchers(*, cd=None, broll=None, hook=None):
    out: dict = {}
    if cd is not None:
        out["dispatch_creative_direction"] = cd
    if broll is not None:
        out["dispatch_broll"] = broll
    if hook is not None:
        out["dispatch_text_hook"] = hook
    return out


def _ok_cd(_guidance):
    return WorkerProposal(proposal_text="plan", beat_plan=PLAN)


def _ok_broll(_guidance):
    return WorkerProposal(proposal_text="broll", new_assets=(_broll_asset(),))


def _ok_hook(_guidance):
    return WorkerProposal(proposal_text="hook", hook=Hook(text="HOOK LINE"))


def _run(strategy, dispatchers, composer):
    strategy.composer = composer
    return strategy.author(
        manifest=_Manifest(), brief="b", dispatchers=dispatchers, brand_kit_tokens=None
    )


def _hook_on() -> ChainConfig:
    return ChainConfig(hook_enabled=True)


def test_happy_path_passes_a_typed_bundle_to_the_composer() -> None:
    composer = StubComposer()
    strategy = ChainStrategy(model_client=object(), config=_hook_on())
    comp = _run(strategy, _dispatchers(cd=_ok_cd, broll=_ok_broll, hook=_ok_hook), composer)

    assert isinstance(comp, Composition)
    resolved = composer.seen["resolved"]
    assert len(resolved) == 1 and resolved[0].asset.asset_id == "asset_b1"
    # With the hook enabled, it is written to composition.hook by reconcile (the text-hook worker's
    # authority), not placed by the Composer.
    assert comp.hook is not None and comp.hook.text == "HOOK LINE"


def test_hook_disabled_by_default_skips_text_hook_and_attaches_no_hook() -> None:
    calls: list = []

    def spy_hook(g):
        calls.append(g)
        return _ok_hook(g)

    composer = StubComposer()
    strategy = ChainStrategy(model_client=object())  # default config: hook_enabled is False
    comp = _run(strategy, _dispatchers(cd=_ok_cd, broll=_ok_broll, hook=spy_hook), composer)

    assert calls == []  # the text-hook worker was never dispatched
    assert comp.hook is None  # no hook attached to the composition


def test_creative_direction_failure_is_fatal() -> None:
    def no_plan(_g):
        return WorkerProposal(proposal_text="oops", beat_plan=None)

    strategy = ChainStrategy(model_client=object())
    with pytest.raises(ChainStageError) as exc:
        _run(strategy, _dispatchers(cd=no_plan, broll=_ok_broll, hook=_ok_hook), StubComposer())
    assert exc.value.stage == "creative-direction"


def test_all_none_assets_still_composes_a_host_cut() -> None:
    def empty_broll(_g):
        return WorkerProposal(proposal_text="nothing", new_assets=())

    composer = StubComposer()
    strategy = ChainStrategy(model_client=object())
    comp = _run(strategy, _dispatchers(cd=_ok_cd, broll=empty_broll, hook=_ok_hook), composer)

    assert isinstance(comp, Composition)
    assert composer.seen["resolved"][0].asset is None  # the hole is explicit, not back-filled


def test_text_hook_failure_degrades() -> None:
    def boom_hook(_g):
        raise RuntimeError("hook worker down")

    composer = StubComposer()
    strategy = ChainStrategy(model_client=object(), config=_hook_on())
    comp = _run(strategy, _dispatchers(cd=_ok_cd, broll=_ok_broll, hook=boom_hook), composer)

    assert isinstance(comp, Composition)
    assert comp.hook is None  # degraded: hook worker failed, run continues


def test_broll_failure_degrades_to_a_hole() -> None:
    def boom_broll(_g):
        raise RuntimeError("broll worker down")

    composer = StubComposer()
    strategy = ChainStrategy(model_client=object())
    comp = _run(strategy, _dispatchers(cd=_ok_cd, broll=boom_broll, hook=_ok_hook), composer)

    assert isinstance(comp, Composition)
    assert composer.seen["resolved"][0].asset is None


def test_composer_failure_is_fatal() -> None:
    strategy = ChainStrategy(model_client=object())
    with pytest.raises(ChainStageError) as exc:
        _run(strategy, _dispatchers(cd=_ok_cd, broll=_ok_broll, hook=_ok_hook),
             StubComposer(raise_error=True))
    assert exc.value.stage == "compose"
