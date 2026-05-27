"""Builder ops exposed as model tool schemas, with fidelity-preserving dispatch (Phase 8, ADR 0004).

The agent authors by calling well-typed tools, one op per turn; each tool wraps an entity-complete
Builder op (Phases 4-6) so the model never emits raw Composition JSON. Two invariants keep the tool
surface honest:

- the enum choices in every tool's input schema are *derived from the kernel enums* (LayoutName,
  RegionName, CaptionStyle, TransitionKind, the overlay ``type`` union), so a tool cannot offer a
  value the kernel would reject (maintainer story 29); and
- ``apply_op`` dispatches a tool call straight onto the matching Builder method, so a tool call with
  given arguments produces the same mutation and OpResult as calling the Builder op directly.

This module is pure kernel-adjacent glue: it imports the Builder and Composition types and builds
overlays through the kernel's own discriminated union, but knows nothing of the loop, perception,
backend, or any model SDK. The vision tools (``render_still``/``scene_preview``) and the terminal
``finish`` tool are declared here but dispatched by the loop, which owns the backend and the gate.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

from pydantic import TypeAdapter

from videogen.agent.model import ToolSpec
from videogen.kernel.builder import Builder, OpResult, TranscriptLike
from videogen.kernel.composition import (
    CaptionStyle,
    LayoutName,
    Overlay,
    RegionName,
    TransitionKind,
)

_OVERLAY_TYPES = ("zoom", "pan", "insert")
_overlay_adapter: TypeAdapter[Overlay] = TypeAdapter(Overlay)


def _choices(enum_cls: type[StrEnum]) -> list[str]:
    """The wire values of a kernel StrEnum, in declared order -- the tool's allowed choices."""
    return [member.value for member in enum_cls]


# --- classification: the loop routes by these sets (mutating ops go through apply_op) ---

MUTATING_OPS = {
    "add_scene",
    "fill_region",
    "add_overlay",
    "add_caption",
    "add_captions_from_transcript",
    "set_transition",
}
VISION_OPS = {"render_still", "scene_preview"}
FINISH_OP = "finish"


def build_overlay(args: dict[str, object]) -> Overlay:
    """Construct the right Overlay subclass from a tool call's flat args.

    The model sends the shared envelope fields (``type``/``start``/``end``/``target``/``z``) plus a
    type-specific ``params`` object; we flatten them and let the kernel's discriminated union pick
    and validate the subclass (zoom/pan/insert), so overlay construction reuses the contract types
    rather than re-deriving them here.
    """
    params = cast(dict[str, object], args.get("params") or {})
    payload: dict[str, object] = {
        "type": args["type"],
        "start": args["start"],
        "end": args["end"],
        **params,
    }
    if "target" in args:
        payload["target"] = args["target"]
    if "z" in args:
        payload["z"] = args["z"]
    return _overlay_adapter.validate_python(payload)


def apply_op(
    builder: Builder,
    name: str,
    args: dict[str, object],
    *,
    transcript: TranscriptLike,
) -> OpResult:
    """Dispatch one mutating tool call onto the matching Builder op and return its OpResult.

    Enum-valued args arrive as their wire strings and are coerced to the kernel enums before the
    call, so a tool dispatch is indistinguishable from the equivalent direct Builder call (the
    fidelity guarantee). ``transcript`` backs ``add_captions_from_transcript`` -- it is the session
    fact (held on the Media Manifest), not a tool argument.
    """
    if name == "add_scene":
        return builder.add_scene(
            LayoutName(cast(str, args["layout"])),
            cast(float, args["start"]),
            cast(float, args["end"]),
            id=cast("str | None", args.get("id")),
            layout_params=cast("dict[str, float] | None", args.get("layout_params")),
        )
    if name == "fill_region":
        return builder.fill_region(
            cast(str, args["scene_id"]),
            RegionName(cast(str, args["region"])),
            cast(str, args["asset_id"]),
            in_point=cast("float | None", args.get("in_point")),
        )
    if name == "add_overlay":
        return builder.add_overlay(build_overlay(args))
    if name == "add_caption":
        return builder.add_caption(
            cast(str, args["text"]),
            cast(float, args["start"]),
            cast(float, args["end"]),
            CaptionStyle(cast(str, args.get("style", CaptionStyle.pill.value))),
        )
    if name == "add_captions_from_transcript":
        return builder.add_captions_from_transcript(
            transcript,
            style=CaptionStyle(cast(str, args.get("style", CaptionStyle.pill.value))),
        )
    if name == "set_transition":
        return builder.add_transition(
            cast(str, args["after_scene"]),
            TransitionKind(cast(str, args.get("kind", TransitionKind.crossfade.value))),
            duration=cast(float, args.get("duration", 0.5)),
        )
    raise KeyError(f"not a mutating tool: {name!r}")


def _number(description: str) -> dict[str, object]:
    return {"type": "number", "description": description}


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="add_scene",
        description=(
            "Append a Scene to the ordered base layer over [start, end) with a layout. The scene "
            "fills no regions yet -- call fill_region next. Spans must fit within the voiceover."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layout": {"type": "string", "enum": _choices(LayoutName)},
                "start": _number("scene start, seconds on the timeline"),
                "end": _number("scene end, seconds (> start, <= voiceover duration)"),
                "id": {"type": "string", "description": "optional stable id; assigned if omitted"},
                "layout_params": {
                    "type": "object",
                    "description": "layout preset params, e.g. split-h's ratio",
                },
            },
            "required": ["layout", "start", "end"],
        },
    ),
    ToolSpec(
        name="fill_region",
        description="Place an asset reference into a region of a scene (overwrites any existing).",
        input_schema={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "region": {"type": "string", "enum": _choices(RegionName)},
                "asset_id": {"type": "string"},
                "in_point": _number("optional source in-point, seconds"),
            },
            "required": ["scene_id", "region", "asset_id"],
        },
    ),
    ToolSpec(
        name="add_overlay",
        description=(
            "Add an effect overlay. zoom/pan are transforms on a base region; insert is floating "
            "b-roll (its params carry asset/anchor/scale). target defaults to the full frame."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(_OVERLAY_TYPES)},
                "start": _number("overlay start, seconds"),
                "end": _number("overlay end, seconds"),
                "target": {"type": "string", "enum": _choices(RegionName)},
                "z": {"type": "integer", "description": "paint order; higher sits on top"},
                "params": {
                    "type": "object",
                    "description": (
                        "type-specific: zoom {from_scale,to_scale}; pan {dx,dy}; "
                        "insert {asset,anchor,scale,in_point,fade}"
                    ),
                },
            },
            "required": ["type", "start", "end"],
        },
    ),
    ToolSpec(
        name="add_caption",
        description="Append one caption to the dedicated captions track within the voiceover span.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "start": _number("caption start, seconds"),
                "end": _number("caption end, seconds"),
                "style": {"type": "string", "enum": _choices(CaptionStyle)},
            },
            "required": ["text", "start", "end"],
        },
    ),
    ToolSpec(
        name="add_captions_from_transcript",
        description=(
            "Lay down the whole word-synced caption track from the transcript in one op (one "
            "caption per word). Restyle individual captions after where the brief wants emphasis."
        ),
        input_schema={
            "type": "object",
            "properties": {"style": {"type": "string", "enum": _choices(CaptionStyle)}},
            "required": [],
        },
    ),
    ToolSpec(
        name="set_transition",
        description="Set a non-cut transition on the boundary after a scene (cut is the default).",
        input_schema={
            "type": "object",
            "properties": {
                "after_scene": {"type": "string"},
                "kind": {"type": "string", "enum": _choices(TransitionKind)},
                "duration": _number("transition duration, seconds"),
            },
            "required": ["after_scene"],
        },
    ),
    ToolSpec(
        name="render_still",
        description=(
            "Render a single still frame at absolute second t and return it as an image. Use "
            "sparingly to confirm framing/occlusion at a moment you are unsure about."
        ),
        input_schema={
            "type": "object",
            "properties": {"t": _number("timeline second to sample")},
            "required": ["t"],
        },
    ),
    ToolSpec(
        name="scene_preview",
        description=(
            "Render a strip of sampled still frames across one scene's span and return them as "
            "images, to judge how the scene reads without paying for a full render."
        ),
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"],
        },
    ),
    ToolSpec(
        name="finish",
        description=(
            "Signal the edit is complete. The loop runs the submit-render gate: if hard errors "
            "remain it reports them and you keep going; if clean, authoring terminates."
        ),
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
]
