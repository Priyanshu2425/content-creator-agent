"""The Composer: single no-tools call -> Composition, with a bounded validate/role-check re-prompt
(ADR 0013, slices 02/04/07). A scripted model stub stands in for Opus 4.8; tests assert behavior
(what it returns, when it re-prompts, when it gives up), never prompt wording.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from videogen.agent.beat_plan import AssetSpec, Beat
from videogen.agent.chain.composer import Composer, ComposerError
from videogen.agent.chain.prep import ResolvedBeat
from videogen.agent.model import AssistantTurn
from videogen.agent.dispatch import NewAsset
from videogen.kernel.composition import Asset, AssetType


@dataclass(frozen=True)
class _Fact:
    id: str
    type: str
    source: str


@dataclass(frozen=True)
class _Manifest:
    voiceover: str = "host"
    duration: float = 2.0
    fps: float = 30.0
    assets: tuple[_Fact, ...] = (_Fact("host", "video", "host.mp4"),)
    transcript: object = None


@dataclass
class ScriptedClient:
    """Returns the queued replies in order; records how many turns were requested."""

    replies: list[str]
    calls: int = field(default=0)

    def next_turn(self, *, system, history, tools) -> AssistantTurn:
        self.calls += 1
        text = self.replies.pop(0) if self.replies else ""
        return AssistantTurn(text=text)


def _host_only_json() -> str:
    return json.dumps(
        {
            "voiceover": {"asset": "host"},
            "assets": {"host": {"type": "video", "src": "host.mp4"}},
            "scenes": [
                {"id": "s0", "start": 0.0, "end": 2.0, "layout": "full",
                 "regions": {"full": {"asset": "host"}}}
            ],
        }
    )


def _beat_keyed(beat_id: str, role: str, start: float, end: float) -> ResolvedBeat:
    return ResolvedBeat(
        beat=Beat(id=beat_id, transcript_span=(0, 0), role=role, intent="x",
                  asset_spec=AssetSpec(kind="broll-image")),
        start_s=start,
        end_s=end,
        asset=NewAsset(asset_id=f"asset_{beat_id}",
                       asset=Asset(type=AssetType.image, src=f"{beat_id}.png"),
                       beat_id=beat_id),
    )


def test_host_only_walking_skeleton() -> None:
    client = ScriptedClient([_host_only_json()])
    comp = Composer(client=client).compose(manifest=_Manifest(), brief="b", resolved_beats=[])
    assert len(comp.scenes) == 1
    assert comp.scenes[0].regions[next(iter(comp.scenes[0].regions))].asset == "host"
    assert client.calls == 1


def test_invalid_output_triggers_a_bounded_reprompt() -> None:
    client = ScriptedClient(["this is not json", _host_only_json()])
    comp = Composer(client=client, max_attempts=3).compose(
        manifest=_Manifest(), brief="b", resolved_beats=[]
    )
    assert comp.scenes  # recovered on the second attempt
    assert client.calls == 2


def test_exhausting_retries_raises_composer_error() -> None:
    client = ScriptedClient(["nope", "still nope", "nope again"])
    with pytest.raises(ComposerError):
        Composer(client=client, max_attempts=3).compose(
            manifest=_Manifest(), brief="b", resolved_beats=[]
        )
    assert client.calls == 3


def test_wrong_role_placement_triggers_a_reprompt() -> None:
    beats = [_beat_keyed("b1", "climax", 0.5, 1.5), _beat_keyed("b2", "resolution", 1.5, 2.0)]
    # Reply 1 places the climax asset on the resolution span (forbidden); reply 2 fixes it.
    bad = json.dumps(
        {
            "voiceover": {"asset": "host"},
            "scenes": [
                {"id": "s0", "start": 1.5, "end": 2.0, "layout": "full",
                 "regions": {"full": {"asset": "asset_b1"}}}
            ],
        }
    )
    good = json.dumps(
        {
            "voiceover": {"asset": "host"},
            "scenes": [
                {"id": "s0", "start": 0.0, "end": 1.5, "layout": "full",
                 "regions": {"full": {"asset": "asset_b1"}}},
                {"id": "s1", "start": 1.5, "end": 2.0, "layout": "full",
                 "regions": {"full": {"asset": "asset_b2"}}},
            ],
        }
    )
    client = ScriptedClient([bad, good])
    comp = Composer(client=client, max_attempts=3).compose(
        manifest=_Manifest(), brief="b", resolved_beats=beats
    )
    assert client.calls == 2
    assert len(comp.scenes) == 2
