"""The Composer: the chain pipeline's terminal agent (ADR 0013).

A single **no-tools** model call (Opus 4.8 via the Claude Code SDK in the default wiring) that emits a
``Composition`` *directly* from a deterministically-prepared bundle. It authors at the Composition
layer -- above the kernel, never a kernel op -- so ADR 0008's "the Director is the only kernel-op
author" still holds literally; this is a different agent in a different pipeline.

The Composer does LLM-decided placement (the chain knowingly opted out of the director-loop's
deterministic ``execute``), but everything with a ground-truth answer is handed to it already solved:
the prep step paired each beat with its asset and resolved its span to seconds. The Composer decides
only *region / layout / treatment / gap-fill*. Two guards run on its output and drive a bounded
re-prompt: the kernel IR validator, and the wrong-role back-fill predicate (ADR 0012's one diagnosed
failure). Exhausting the retries is a fatal Composer failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from videogen import log
from videogen.agent.chain.prep import ResolvedBeat
from videogen.agent.chain.role_check import wrong_role_backfill_violations
from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ModelClient,
    UserMessage,
)
from videogen.agent.perception import Manifest
from videogen.kernel.composition import Asset, AssetType, Audio, Composition
from videogen.kernel.validator import validate

SYSTEM_PROMPT = """\
You are the Composer: the final author of a vertical (9:16) short-form video, emitted as a single
declarative Composition JSON document. You do NOT call tools. You output exactly one JSON object and
nothing else.

You are given a prepared bundle: the voiceover (master clock), the available assets, and an ordered
list of BEATS. Each beat already carries the concrete seconds it occupies (start_s/end_s) and, when an
asset was generated for it, that asset's id. Your job is judgment only -- place each beat's asset in
the timeline within its [start_s, end_s] window, in beat order, and assemble a coherent timeline.

Hard rules:
- Output ONLY the Composition JSON object. No prose, no markdown fence.
- The composition MUST include "voiceover": {"asset": "<voiceover id>"} and reference only assets that
  exist in the bundle's asset library.
- Scenes may not overlap and are ordered by start. Use layout "full" with region "full".
- B-ROLL DURATION CAP: a b-roll/motion-graphic/stat-viz asset must NOT stay on screen longer than
  **1.5 seconds**. If a beat's [start_s, end_s] window is longer than 1.5s, do NOT hold the b-roll for
  the whole window -- give the b-roll a scene of at most ~1.5s, then cut back to the host (voiceover)
  asset for the remainder of that window (or split into two different b-roll scenes if two assets
  serve the beat). A held b-roll past 1.5s is a dead frame. The host/a-roll may run longer; only b-roll
  is capped.
- NEVER place an asset on a beat span whose role differs from the role the asset was generated for.
  An asset made for a "climax" beat must not land on a "resolution" span. Honor each asset's beat.
- A beat marked role "host-aroll" (or asset kind "host-aroll") is the talking head: fill its scene
  with the voiceover/host asset, not a generated asset.
- For a beat whose asset is null (a hole), do NOT back-fill a different-role asset. Either hold the
  host on that span or drop the beat.
- Do NOT author the opening text-hook or any captions -- those are filled deterministically after you
  by the reconcile step. Leave "captions" empty and never emit a "title" overlay.
- If there are no beats and no generated assets, emit a single full host scene spanning the whole
  duration (the host-only cut).

Composition shape (fields you author):
{
  "voiceover": {"asset": "<id>"},
  "assets": {"<id>": {"type": "video|image|audio", "src": "<path>"}},
  "scenes": [{"id": "s0", "start": 0.0, "end": 2.0, "layout": "full",
              "regions": {"full": {"asset": "<id>"}}}],
  "overlays": [],
  "captions": []
}
"""


class ComposerError(RuntimeError):
    """The Composer could not produce a valid Composition within its retry budget (ADR 0013)."""


@dataclass
class Composer:
    """Turns a prepared bundle into a Composition with a bounded validate/role-check re-prompt loop."""

    client: ModelClient
    max_attempts: int = 3
    system: str = SYSTEM_PROMPT

    def compose(
        self,
        *,
        manifest: Manifest,
        brief: str,
        resolved_beats: list[ResolvedBeat],
        brand_kit_tokens: dict[str, Any] | None = None,
        extra_assets: tuple[Any, ...] = (),
    ) -> Composition:
        """Emit a validated Composition. ``extra_assets`` are non-beat-keyed ``NewAsset``s (e.g.
        unbound motion-graphics) the Composer may use as supporting visuals. The opening hook and
        captions are NOT authored here -- the reconcile step fills them after (ADR 0013)."""
        library = _asset_library(manifest, resolved_beats, extra_assets)
        bundle = _build_bundle(
            manifest=manifest,
            brief=brief,
            resolved_beats=resolved_beats,
            brand_kit_tokens=brand_kit_tokens,
            library=library,
        )
        history: list[HistoryItem] = [UserMessage(text=bundle)]

        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            turn: AssistantTurn = self.client.next_turn(
                system=self.system, history=history, tools=[]
            )
            text = turn.text or ""
            try:
                composition = _parse_composition(text, library, manifest.voiceover)
            except (ValueError, KeyError) as exc:
                last_error = f"the output was not a valid Composition: {exc}"
                history += [turn, UserMessage(text=_retry_message(last_error))]
                log.get().agent_event_complete("composer-parse-retry", duration_ms=0)
                continue

            problems = _problems(composition, manifest, resolved_beats)
            if not problems:
                log.get().agent_event_complete("composer", duration_ms=0, attempts=attempt)
                return composition
            last_error = "; ".join(problems)
            history += [turn, UserMessage(text=_retry_message(last_error))]
            log.get().agent_event_complete("composer-validate-retry", duration_ms=0)

        raise ComposerError(
            f"Composer failed to produce a valid Composition in {self.max_attempts} attempts; "
            f"last problem: {last_error}"
        )


def _problems(
    composition: Composition, manifest: Manifest, resolved_beats: list[ResolvedBeat]
) -> list[str]:
    """Collect the blocking issues with a candidate Composition: IR-validator errors first, then any
    wrong-role back-fill violations (ADR 0012)."""
    problems: list[str] = []
    report = validate(composition, duration=manifest.duration)
    problems += [f"validator[{e.code}]: {e.message}" for e in report.errors]
    problems += [v.describe() for v in wrong_role_backfill_violations(composition, resolved_beats)]
    return problems


def _retry_message(problem: str) -> str:
    return (
        "Your previous Composition was rejected. Fix these problems and output the corrected "
        f"Composition JSON only (no prose):\n{problem}"
    )


def _asset_library(
    manifest: Manifest, resolved_beats: list[ResolvedBeat], extra_assets: tuple[Any, ...]
) -> dict[str, Asset]:
    """The full asset library available to the Composer: the manifest's declared assets (host +
    supplied b-roll) plus every beat-keyed and extra generated asset."""
    library: dict[str, Asset] = {
        fact.id: Asset(type=AssetType(fact.type), src=fact.source) for fact in manifest.assets
    }
    for rb in resolved_beats:
        if rb.asset is not None:
            library[rb.asset.asset_id] = rb.asset.asset
    for na in extra_assets:
        library[na.asset_id] = na.asset
    return library


def _build_bundle(
    *,
    manifest: Manifest,
    brief: str,
    resolved_beats: list[ResolvedBeat],
    brand_kit_tokens: dict[str, Any] | None,
    library: dict[str, Asset],
) -> str:
    """Serialize the typed bundle the Composer authors from. Typed-only -- no prose scratchpad."""
    beats = [
        {
            "beat_id": rb.beat.id,
            "role": rb.beat.role,
            "intent": rb.beat.intent,
            "start_s": round(rb.start_s, 3),
            "end_s": round(rb.end_s, 3),
            "asset_kind": rb.beat.asset_spec.kind,
            "asset_id": rb.asset.asset_id if rb.asset is not None else None,
            "is_hole": rb.is_hole,
        }
        for rb in resolved_beats
    ]
    payload = {
        "brief": brief,
        "voiceover_asset": manifest.voiceover,
        "duration_s": round(manifest.duration, 3),
        "fps": manifest.fps,
        "asset_library": {aid: {"type": a.type.value, "src": a.src} for aid, a in library.items()},
        "beats": beats,
        "brand_kit": brand_kit_tokens,
    }
    return "Compose the Composition for this video.\n\n" + json.dumps(payload, indent=2)


def _parse_composition(
    text: str, library: dict[str, Asset], voiceover_id: str
) -> Composition:
    """Parse the model's reply into a Composition, back-filling the voiceover and any referenced-but-
    undeclared assets from the known library so a model that forgets a declaration still validates.

    This is a deterministic safety net, not placement: it never invents a scene or chooses where an
    asset goes -- it only ensures the asset *declarations* and the master-clock voiceover are present.
    """
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")

    data.setdefault("voiceover", {"asset": voiceover_id})
    assets = data.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("'assets' must be an object")
    for aid in _referenced_asset_ids(data) | {data["voiceover"].get("asset", voiceover_id)}:
        if aid and aid not in assets and aid in library:
            asset = library[aid]
            assets[aid] = {"type": asset.type.value, "src": asset.src}

    return Composition.model_validate(data)


def _referenced_asset_ids(data: dict) -> set[str]:
    """Every asset id referenced by scenes/overlays in the raw composition dict."""
    ids: set[str] = set()
    for scene in data.get("scenes", []) or []:
        for ref in (scene.get("regions", {}) or {}).values():
            if isinstance(ref, dict) and ref.get("asset"):
                ids.add(str(ref["asset"]))
    for overlay in data.get("overlays", []) or []:
        if isinstance(overlay, dict) and overlay.get("asset"):
            ids.add(str(overlay["asset"]))
    return ids


def _extract_json(text: str) -> Any:
    """Pull a single JSON object out of the reply, tolerating a ``` fence or surrounding prose."""
    stripped = text.strip()
    if "```" in stripped:
        fenced = stripped.split("```")
        for chunk in fenced:
            c = chunk.strip()
            if c.lower().startswith("json"):
                c = c[4:].strip()
            if c.startswith("{"):
                stripped = c
                break
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in the Composer reply")
        return json.loads(stripped[start : end + 1])
