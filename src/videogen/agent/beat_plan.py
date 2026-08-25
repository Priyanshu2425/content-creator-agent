"""The typed creative-direction proposal: a BeatPlan binds intent to placement (ADR 0012).

A ``BeatPlan`` is the creative-direction worker's proposal expressed in **domain terms** -- no kernel
scene/region/op concepts -- so the worker stays kernel-agnostic (ADR 0001/0002). Each ``Beat`` carries
a stable ``id`` that is threaded through asset generation (a generated asset is tagged with the beat it
serves), so the Director places assets by lookup rather than by re-reading their text descriptions.

The ``transcript_span`` is anchored to **transcript word indices** -- the *when* the Director already
owns -- not seconds, so a beat's timing survives re-timing of the underlying audio.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetSpec:
    """What a beat needs on screen. ``kind`` selects the generator (or, for ``host-aroll``, binds the
    existing talking-head track and carries no generation brief)."""

    kind: str  # broll-image | broll-video | motion-graphic | host-aroll | stat-viz
    brief: str = ""
    treatment: str = ""


@dataclass(frozen=True)
class Beat:
    """One narrative moment: a stable id, when it happens (word indices), its role in the arc, a
    one-line intent, and the asset that serves it."""

    id: str
    transcript_span: tuple[int, int]  # [start_word_idx, end_word_idx], inclusive
    role: str  # world-1 | world-2 | climax | resolution | cta | ...
    intent: str
    asset_spec: AssetSpec


@dataclass(frozen=True)
class BeatPlan:
    """An ordered list of beats -- the creative-direction proposal the Director executes."""

    beats: tuple[Beat, ...]


def beat_plan_from_dict(data: dict) -> BeatPlan:
    """Build a BeatPlan from a parsed JSON object (the creative-direction worker's structured output).

    Shape::

        {"beats": [{"id": "b1", "transcript_span": [4, 12], "role": "climax",
                    "intent": "the payoff lands",
                    "asset_spec": {"kind": "broll-image", "brief": "...", "treatment": "..."}}]}

    Tolerant of the small shape slips a model makes: a ``transcript_span`` that is a single value or
    has the wrong length is coerced rather than raising ``IndexError``, and missing ``id``/``role`` fall
    back to sensible defaults. A beat with no ``asset_spec`` at all is skipped (it cannot be placed).
    """
    beats: list[Beat] = []
    for i, raw in enumerate(data.get("beats", [])):
        spec = raw.get("asset_spec")
        if not isinstance(spec, dict) or not str(spec.get("kind", "")).strip():
            continue  # a beat with no asset kind can't drive placement
        beats.append(
            Beat(
                id=str(raw.get("id") or f"b{i + 1}"),
                transcript_span=_coerce_span(raw.get("transcript_span")),
                role=str(raw.get("role", "")).strip() or "world-1",
                intent=str(raw.get("intent", "")),
                asset_spec=AssetSpec(
                    kind=str(spec["kind"]).strip(),
                    brief=str(spec.get("brief", "")),
                    treatment=str(spec.get("treatment", "")),
                ),
            )
        )
    return BeatPlan(beats=tuple(beats))


def _coerce_span(value: object) -> tuple[int, int]:
    """Coerce a model's ``transcript_span`` into an inclusive (start, end) word-index pair.

    Accepts a 2+ element list (first two used), a single value (start==end), or a bare int. Anything
    else falls back to (0, 0). Out-of-range indices are clamped later against the real transcript
    (the chain prep step / beat_execute), so this only needs to avoid raising."""
    try:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2:
                return (int(value[0]), int(value[1]))
            if len(value) == 1:
                v = int(value[0])
                return (v, v)
        elif isinstance(value, (int, float)):
            v = int(value)
            return (v, v)
    except (TypeError, ValueError):
        pass
    return (0, 0)


class BeatPlanParseError(ValueError):
    """Raised when a model response cannot be coerced into a well-formed BeatPlan (ADR 0013)."""


def parse_beat_plan(raw: str | dict | list, *, n_words: int) -> BeatPlan:
    """Tolerant model-output -> BeatPlan coercion for the chain pipeline (ADR 0013).

    Unlike the strict ``beat_plan_from_dict``, this accepts a JSON string (optionally ``` fenced),
    a ``{"beats": [...]}`` object, or a bare list, and clamps each ``transcript_span`` into
    ``[0, n_words-1]`` (ordered low->high) so a sloppy model can't place an asset off the timeline.
    An empty/blank plan or a beat missing ``asset_spec.kind`` raises ``BeatPlanParseError`` -- the
    chain treats that as a fatal creative-direction failure, never a silent empty plan.
    """
    import json

    data: object = raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            nl = text.find("\n")
            if nl != -1 and text[:nl].strip().lower() in {"json", ""}:
                text = text[nl + 1 :]
            text = text.strip().rstrip("`").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end <= start:
                raise BeatPlanParseError("response was not valid JSON and held no JSON object")
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise BeatPlanParseError(f"could not parse BeatPlan JSON: {exc}") from exc

    items = data.get("beats", []) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise BeatPlanParseError("BeatPlan carries no beats")
    if n_words <= 0:
        raise BeatPlanParseError("cannot resolve beats against an empty transcript")

    last = n_words - 1
    beats: list[Beat] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise BeatPlanParseError(f"beat #{i} is not an object: {item!r}")
        spec = item.get("asset_spec") or {}
        if not isinstance(spec, dict) or not str(spec.get("kind", "")).strip():
            raise BeatPlanParseError(f"beat #{i} requires asset_spec.kind")
        span_raw = item.get("transcript_span")
        if not isinstance(span_raw, (list, tuple)) or len(span_raw) != 2:
            raise BeatPlanParseError(f"beat #{i} transcript_span must be [start, end] word indices")
        try:
            lo, hi = sorted((int(span_raw[0]), int(span_raw[1])))
        except (TypeError, ValueError):
            raise BeatPlanParseError(f"beat #{i} transcript_span must be integers")
        beats.append(
            Beat(
                id=str(item.get("id") or f"b{i + 1}").strip(),
                transcript_span=(max(0, min(lo, last)), max(0, min(hi, last))),
                role=str(item.get("role", "")).strip() or "world-1",
                intent=str(item.get("intent", "")).strip(),
                asset_spec=AssetSpec(
                    kind=str(spec["kind"]).strip(),
                    brief=str(spec.get("brief", "")).strip(),
                    treatment=str(spec.get("treatment", "")).strip(),
                ),
            )
        )
    return BeatPlan(beats=tuple(beats))
