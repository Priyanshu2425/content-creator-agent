"""Structured perception: the Media Manifest and the always-on perception packet (Phase 8, 0004).

After every op the authoring loop hands the agent a text packet that is the union of four channels:
the **Media Manifest** (stable session facts -- assets, the voiceover master clock, fps, and the
word-timed transcript), the **current Composition**, the **Resolver textual timeline**, and the
**validation report**. This is the agent's cheapest, always-available sense; pixel-level vision is
the separate, agent-triggered channel (the loop's ``render_still``/``scene_preview``).

The Manifest is a *structural* type (a Protocol): AuthoringService depends on the shape, not on
MediaService, so the producer stays a sibling that merely satisfies it (ADR 0003 boundary). A
concrete ``MediaManifest`` is provided for callers/tests to populate from probe + transcript facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import gcd
from typing import Protocol

from videogen.kernel import resolver
from videogen.kernel.builder import TranscriptLike
from videogen.kernel.composition import Composition
from videogen.kernel.validator import ValidationResult, validate


@dataclass(frozen=True)
class AssetFact:
    """One asset as the agent perceives it: identity plus the objective probe facts (no creative
    interpretation, ADR 0003). ``duration``/``width``/``height`` are absent for assets that lack
    them (e.g. a still image carries no duration). ``description`` and ``usage_advice`` are
    populated by the optional GeminiDescribeAgent before authoring begins."""

    id: str
    type: str
    source: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    description: str | None = None
    usage_advice: str | None = None


class Manifest(Protocol):
    """The session facts the agent plans against, held stable for the run. Structural so any
    producer (MediaService, a test, the CLI) satisfies it without an import cycle."""

    @property
    def assets(self) -> Sequence[AssetFact]: ...
    @property
    def voiceover(self) -> str: ...
    @property
    def duration(self) -> float: ...
    @property
    def fps(self) -> float: ...
    @property
    def transcript(self) -> TranscriptLike: ...


@dataclass(frozen=True)
class MediaManifest:
    """A concrete Manifest. Callers build it from MediaService's probe + transcript facts."""

    assets: tuple[AssetFact, ...]
    voiceover: str
    duration: float
    fps: float
    transcript: TranscriptLike


def assemble_perception(composition: Composition, manifest: Manifest) -> str:
    """Assemble the structured perception packet for the current document against the manifest.

    The voiceover sets the duration (master clock, ADR 0005), so the manifest's duration drives both
    the timeline render and the validation pass -- the agent always reads the document validated at
    the real length of the recording.
    """
    duration = manifest.duration
    sections = [
        _manifest_section(manifest),
        "## Composition\n" + composition.model_dump_json(by_alias=True),
        "## Timeline\n" + resolver.timeline(composition, duration=duration),
        _validation_section(validate(composition, duration=duration)),
    ]
    return "\n\n".join(sections)


def _shape(width: int | None, height: int | None) -> str:
    """A compact ``WxH (A:B portrait)`` descriptor so the agent can reason about fit, not just raw
    pixels: the reduced aspect ratio plus an orientation word (the cue it needs to pick a layout).
    """
    if not width or not height:
        return ""
    divisor = gcd(width, height)
    aspect = f"{width // divisor}:{height // divisor}"
    if width > height:
        orientation = "landscape"
    elif width < height:
        orientation = "portrait"
    else:
        orientation = "square"
    return f" {width}x{height} ({aspect} {orientation})"


def _canvas_line(manifest: Manifest) -> str | None:
    """The output frame's shape, taken from the voiceover (host) asset -- the master that fixes the
    canvas. The agent needs this to know how each asset will be cropped to ``cover`` a region."""
    host = next((a for a in manifest.assets if a.id == manifest.voiceover), None)
    if host is None or not host.width or not host.height:
        return None
    return f"output canvas:{_shape(host.width, host.height)}"


def _manifest_section(manifest: Manifest) -> str:
    lines = [
        "## Media Manifest",
        f"voiceover: {manifest.voiceover} (master clock) · "
        f"duration {manifest.duration:.2f}s · {manifest.fps:.0f}fps",
    ]
    canvas = _canvas_line(manifest)
    if canvas is not None:
        lines.append(canvas)
    lines.append("assets:")
    for asset in manifest.assets:
        dims = _shape(asset.width, asset.height)
        dur = f" {asset.duration:.2f}s" if asset.duration is not None else ""
        lines.append(f"  {asset.id} · {asset.type} · {asset.source}{dims}{dur}")
        if asset.description:
            lines.append(f"    description: {asset.description}")
        if asset.usage_advice:
            lines.append(f"    usage advice: {asset.usage_advice}")
    words = len(manifest.transcript.words)
    lines.append(f"transcript ({words} words): {_transcript_text(manifest)}")
    return "\n".join(lines)


def _transcript_text(manifest: Manifest) -> str:
    return " ".join(word.text for word in manifest.transcript.words)


def _validation_section(result: ValidationResult) -> str:
    lines = ["## Validation", f"submit gate: {'PASS' if result.ok else 'BLOCKED'}"]
    if result.errors:
        lines.append("errors:")
        lines.extend(f"  [{error.code.value}] {error.message}" for error in result.errors)
    if result.warnings:
        lines.append("warnings:")
        lines.extend(f"  [{warning.code.value}] {warning.message}" for warning in result.warnings)
    if not result.errors and not result.warnings:
        lines.append("clean: no errors, no warnings")
    return "\n".join(lines)
