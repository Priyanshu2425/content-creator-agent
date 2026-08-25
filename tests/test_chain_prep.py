"""Prep step: zip beats to assets + resolve word-index spans to seconds (ADR 0013, chain slice 03).

Pure module -- a fake BeatPlan + stub assets + a word-timed transcript fully exercise it. These tests
assert *what* prep produces (pairs, holes, seconds, order), never how it loops.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.beat_plan import AssetSpec, Beat, BeatPlan
from videogen.agent.chain.prep import prep
from videogen.agent.dispatch import NewAsset
from videogen.kernel.composition import Asset, AssetType


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


# words 0..3 span 0.0s -> 2.0s in half-second steps.
TRANSCRIPT = _Transcript(
    [
        _Word("the", 0.0, 0.5),
        _Word("payoff", 0.5, 1.0),
        _Word("arrives", 1.0, 1.5),
        _Word("now", 1.5, 2.0),
    ]
)


def _beat(beat_id: str, span: tuple[int, int], role: str = "climax", kind: str = "broll-image") -> Beat:
    return Beat(
        id=beat_id,
        transcript_span=span,
        role=role,
        intent="x",
        asset_spec=AssetSpec(kind=kind),
    )


def _asset(beat_id: str) -> NewAsset:
    return NewAsset(
        asset_id=f"asset_{beat_id}",
        asset=Asset(type=AssetType.image, src=f"{beat_id}.png"),
        description="b-roll",
        beat_id=beat_id,
    )


def test_matched_beat_gets_its_asset_and_resolved_span() -> None:
    plan = BeatPlan(beats=(_beat("b1", (1, 2)),))  # "payoff arrives" -> 0.5s..1.5s
    resolved = prep(plan, [_asset("b1")], TRANSCRIPT)

    assert len(resolved) == 1
    rb = resolved[0]
    assert rb.asset is not None and rb.asset.asset_id == "asset_b1"
    assert (rb.start_s, rb.end_s) == (0.5, 1.5)
    assert rb.is_hole is False


def test_missing_asset_becomes_an_explicit_none_hole() -> None:
    plan = BeatPlan(beats=(_beat("b1", (0, 1)),))
    resolved = prep(plan, [], TRANSCRIPT)  # no assets generated

    assert resolved[0].asset is None
    assert resolved[0].is_hole is True


def test_host_aroll_beat_is_none_but_not_a_hole() -> None:
    plan = BeatPlan(beats=(_beat("h1", (0, 0), role="host-aroll", kind="host-aroll"),))
    resolved = prep(plan, [], TRANSCRIPT)

    assert resolved[0].asset is None
    assert resolved[0].is_hole is False  # host track is its "asset", not a missing generation


def test_order_is_preserved_and_each_span_resolves() -> None:
    plan = BeatPlan(
        beats=(
            _beat("b1", (0, 0)),  # "the" -> 0.0..0.5
            _beat("b2", (3, 3)),  # "now" -> 1.5..2.0
        )
    )
    resolved = prep(plan, [_asset("b2")], TRANSCRIPT)

    assert [rb.beat.id for rb in resolved] == ["b1", "b2"]
    assert (resolved[0].start_s, resolved[0].end_s) == (0.0, 0.5)
    assert (resolved[1].start_s, resolved[1].end_s) == (1.5, 2.0)
    assert resolved[0].asset is None  # b1 unmatched
    assert resolved[1].asset is not None  # b2 matched


def test_assets_may_be_passed_as_a_mapping() -> None:
    plan = BeatPlan(beats=(_beat("b1", (0, 1)),))
    resolved = prep(plan, {"b1": _asset("b1")}, TRANSCRIPT)
    assert resolved[0].asset is not None
