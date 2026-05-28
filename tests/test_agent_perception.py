"""Structured perception: the always-on packet the loop returns after every op (Phase 8, ADR 0004).

The agent's primary, render-free sense. After each op the loop hands back a text packet that is the
union of the Media Manifest (stable session facts), the current Composition, the Resolver textual
timeline, and the two-tier validation report. These tests assert the packet's externally observable
contents -- that it carries each channel and that it surfaces the validator's own verdicts (overlap
as an error, a gap as a warning) -- not its exact formatting.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.perception import AssetFact, MediaManifest, assemble_perception
from videogen.kernel import resolver
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Composition,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


def manifest() -> MediaManifest:
    return MediaManifest(
        assets=(
            AssetFact(
                id="host", type="video", source="host.mp4", duration=4.0, width=1080, height=1920
            ),
        ),
        voiceover="host",
        duration=4.0,
        fps=30.0,
        transcript=_Transcript([_Word("hello", 0.0, 0.5), _Word("world", 0.5, 1.0)]),
    )


def _scene(id: str, start: float, end: float) -> Scene:
    return Scene(
        id=id,
        start=start,
        end=end,
        layout=LayoutName.full,
        regions={RegionName.full: Ref(asset="host")},
    )


def _composition(scenes: list[Scene]) -> Composition:
    return Composition(
        assets={"host": Asset(type=AssetType.video, src="host.mp4")},
        voiceover=Audio(asset="host"),
        scenes=scenes,
    )


def test_packet_carries_every_perception_channel() -> None:
    comp = _composition([_scene("s0", 0.0, 2.0)])

    packet = assemble_perception(comp, manifest())

    assert "host.mp4" in packet  # manifest: the asset source
    assert "hello world" in packet  # manifest: the transcript text
    assert "s0" in packet  # the current composition
    assert resolver.timeline(comp, duration=4.0) in packet  # the resolver timeline verbatim


def test_manifest_surfaces_aspect_orientation_and_the_output_canvas() -> None:
    comp = _composition([_scene("s0", 0.0, 2.0)])

    packet = assemble_perception(comp, manifest())

    # the host asset's reduced aspect + orientation, so the agent can reason about fit (TODO 1)
    assert "1080x1920 (9:16 portrait)" in packet
    # the output frame shape, taken from the voiceover/host asset (what every region is cropped to)
    assert "output canvas: 1080x1920 (9:16 portrait)" in packet


def test_packet_reports_scene_overlap_as_an_error() -> None:
    comp = _composition([_scene("s0", 0.0, 2.0), _scene("s1", 1.0, 3.0)])

    packet = assemble_perception(comp, manifest())

    assert "scene_overlap" in packet  # the local hard-error code, fed back for self-correction


def test_packet_reports_a_gap_as_a_warning() -> None:
    comp = _composition([_scene("s0", 0.0, 2.0)])  # scene ends at 2.0, voiceover runs to 4.0

    packet = assemble_perception(comp, manifest())

    assert "trailing_gap" in packet  # a reported, non-blocking warning
