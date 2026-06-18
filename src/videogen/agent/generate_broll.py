"""GenerateBrollAgent: generates still-image b-roll assets via Nano Banana using a tool-call loop.

Receives the Media Manifest, brief, platform, and an IdealCuts plan; runs a model through
generate_image tool calls dispatched to NanoBananaCreator (Gemini 2.5 Flash Image); returns a
GeneratedBroll with the plan narration and one GeneratedSlot per successful generation.

This agent is image-only: every b-roll asset it produces is a still. Tool calls within a single
turn are dispatched in parallel (ThreadPoolExecutor) so multiple image generations in one turn
are not serialised.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from videogen import log, tracing
from videogen.agent.model import (
    AssistantTurn,
    HistoryItem,
    ModelClient,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from videogen.agent.perception import Manifest
from videogen.agent.stat_viz import DEFAULT_STYLE_BRIEF, StyleBrief, StatVizRenderer
from videogen.creation.nano_banana import NanoBananaCreator

_MAX_OPS = 60  # hard budget: slots * 2 (plan turn + tool turns) with headroom


@dataclass(frozen=True)
class GeneratedSlot:
    """One successfully generated b-roll asset from a tool call."""

    slot_index: int
    kind: Literal["image", "video"]
    path: Path
    prompt: str


@dataclass(frozen=True)
class GeneratedBroll:
    """The full output of a GenerateBrollAgent run."""

    plan_text: str                   # all narration the model emitted across turns
    slots: tuple[GeneratedSlot, ...]  # one per successful generation, in call order


# ---------------------------------------------------------------------------
# Tool schema — image only (Nano Banana); model / aspect handling is fixed below
# ---------------------------------------------------------------------------

_GENERATE_IMAGE_TOOL = ToolSpec(
    name="generate_image",
    description=(
        "Generate a still-image b-roll asset from a text prompt via Nano Banana. "
        "Use for: stat cards, social proof screenshots, headline cards, before/after comparisons, "
        "infographics, UI mockups, establishing stills. "
        "Returns the local file path of the saved image."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {
                "type": "integer",
                "description": "The SLOT number from the GENERATEBROLL PLAN this generation fills.",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Full generation prompt. Must follow prompt engineering rules: "
                    "specify exact text for stat/headline cards, use style anchors "
                    "(e.g. 'bold graphic design', 'clean minimal dark background'), "
                    "never request people, never leave numbers unspecified."
                ),
            },
            "aspect_ratio": {
                "type": "string",
                "description": "e.g. '9:16' for Reels/TikTok, '16:9' for YouTube Shorts.",
            },
        },
        "required": ["slot", "prompt", "aspect_ratio"],
    },
)

_RENDER_COUNTER_TOOL = ToolSpec(
    name="render_counter",
    description=(
        "Generate an animated counter clip for a single numerical or percentage stat claim. "
        "Use for: 'revenue grew 40%', '10x faster', 'saves 3 hours', any claim with ONE key number. "
        "Animates the number counting up to the final value. "
        "Returns the local file path of the saved video clip."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {"type": "integer", "description": "SLOT number from the GENERATEBROLL PLAN."},
            "value": {"type": "number", "description": "The final numeric value to count up to (e.g. 40 for '40%')."},
            "unit": {"type": "string", "description": "Unit string displayed after the value (e.g. '%', 'x', 'hrs', '$M')."},
            "label": {"type": "string", "description": "Supporting label displayed below the number (e.g. 'Revenue Growth')."},
            "duration_s": {"type": "number", "description": "Clip duration in seconds. Match the slot window duration from the IdealCuts plan."},
        },
        "required": ["slot", "value", "unit", "label", "duration_s"],
    },
)

_RENDER_BAR_TOOL = ToolSpec(
    name="render_bar",
    description=(
        "Generate an animated bar comparison clip for two-value comparisons. "
        "Use for: 'Company A: 80%, Company B: 20%', 'before $1M vs after $5M', any claim with TWO comparable values. "
        "Animates two bars filling to their respective values side by side. "
        "Returns the local file path of the saved video clip."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {"type": "integer", "description": "SLOT number from the GENERATEBROLL PLAN."},
            "label_a": {"type": "string", "description": "Label for the first bar (e.g. 'Before', 'Company A')."},
            "value_a": {"type": "number", "description": "Numeric value for the first bar."},
            "label_b": {"type": "string", "description": "Label for the second bar (e.g. 'After', 'Company B')."},
            "value_b": {"type": "number", "description": "Numeric value for the second bar."},
            "unit": {"type": "string", "description": "Shared unit displayed after each value (e.g. '%', '$M')."},
            "duration_s": {"type": "number", "description": "Clip duration in seconds."},
        },
        "required": ["slot", "label_a", "value_a", "label_b", "value_b", "unit", "duration_s"],
    },
)

_RENDER_GAUGE_TOOL = ToolSpec(
    name="render_gauge",
    description=(
        "Generate an animated progress ring clip for progress-toward-a-goal claims. "
        "Use for: 'raised $3M of a $10M goal', '75% complete', '3 out of 4 metrics hit'. "
        "Animates a ring filling from 0 to value/max. max can be any number, not just 100. "
        "Returns the local file path of the saved video clip."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {"type": "integer", "description": "SLOT number from the GENERATEBROLL PLAN."},
            "value": {"type": "number", "description": "Current value (e.g. 3 for '$3M raised')."},
            "max": {"type": "number", "description": "Maximum / goal value (e.g. 10 for '$10M goal'). Can be any positive number."},
            "unit": {"type": "string", "description": "Unit displayed in the centre (e.g. '$M', '%', 'pts')."},
            "label": {"type": "string", "description": "Label displayed below the ring (e.g. 'Funding Goal')."},
            "duration_s": {"type": "number", "description": "Clip duration in seconds."},
        },
        "required": ["slot", "value", "max", "unit", "label", "duration_s"],
    },
)

_RENDER_BEFORE_AFTER_TOOL = ToolSpec(
    name="render_before_after",
    description=(
        "Generate an animated before/after reveal clip for state-change claims, both numeric and qualitative. "
        "Use for: 'manual process → automated', '3 hours → 10 minutes', 'old way → new way'. "
        "Values are STRINGS — pass numeric values as strings (e.g. '3 hours'). "
        "Reveals the before state first, then the after state. "
        "Returns the local file path of the saved video clip."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {"type": "integer", "description": "SLOT number from the GENERATEBROLL PLAN."},
            "label_a": {"type": "string", "description": "Label for the before state (e.g. 'Before', 'Old Way')."},
            "value_a": {"type": "string", "description": "Before value as a string (e.g. '3 hours', 'manual')."},
            "label_b": {"type": "string", "description": "Label for the after state (e.g. 'After', 'New Way')."},
            "value_b": {"type": "string", "description": "After value as a string (e.g. '10 minutes', 'automated')."},
            "duration_s": {"type": "number", "description": "Clip duration in seconds."},
        },
        "required": ["slot", "label_a", "value_a", "label_b", "value_b", "duration_s"],
    },
)

_RENDER_RATIO_TOOL = ToolSpec(
    name="render_ratio",
    description=(
        "Generate an animated ratio icon clip for 'X in N' or 'X out of Y' fraction claims. "
        "Use for: '1 in 3 users churn', '2 out of 5 businesses fail', any fraction-of-a-whole claim. "
        "Animates icons filling in one by one to reveal the ratio. "
        "Returns the local file path of the saved video clip."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot": {"type": "integer", "description": "SLOT number from the GENERATEBROLL PLAN."},
            "numerator": {"type": "integer", "description": "How many out of the total (e.g. 1 for '1 in 3')."},
            "denominator": {"type": "integer", "description": "The total count (e.g. 3 for '1 in 3'). Keep ≤ 10 for readability."},
            "label": {"type": "string", "description": "Supporting label (e.g. 'churn within 90 days')."},
            "duration_s": {"type": "number", "description": "Clip duration in seconds."},
        },
        "required": ["slot", "numerator", "denominator", "label", "duration_s"],
    },
)

_STAT_VIZ_TOOLS = [
    _RENDER_COUNTER_TOOL,
    _RENDER_BAR_TOOL,
    _RENDER_GAUGE_TOOL,
    _RENDER_BEFORE_AFTER_TOOL,
    _RENDER_RATIO_TOOL,
]

_STAT_VIZ_TOOL_NAMES = frozenset(t.name for t in _STAT_VIZ_TOOLS)

_TOOLS = [_GENERATE_IMAGE_TOOL]

_SYSTEM_PROMPT = """\
# SYSTEM PROMPT — BrollGeneratorAgent (worker)

You are **BrollGeneratorAgent**, a worker in a video pipeline orchestrated by **DirectorAgent**. Given a talking-head cut's **timestamped transcript** plus constraints injected by the Director, you produce the **b-roll and overlay layer**: you decide what visual support each moment needs, obtain or create each asset with the correct tool, and return a shot list for the Director to integrate.

You own one layer only. You do **not** set the design language, own the pacing rules, or assemble the final video — those belong to the Director. You respect what it injects and report what you contribute.

---

## 1. Inputs the Director injects (treat as authoritative)

- `transcript` — timestamped.
- `brand_kit` — fonts, colors, logo treatment, motion, safe zones, aspect/width/height/fps. Style every asset to these tokens. Do not invent your own look.
- `pacing_budget` — `{ target_change_interval_seconds, max_static_gap_seconds, min_change_interval_seconds, first_seconds_priority }`. Respect it locally; do not exceed the density floor; keep the opening hook window clear.
- `timeline_context` — change timestamps already provided by other layers (hard cuts, caption cadence, the reserved 0–3s hook window). Use this so you don't stack a redundant insert on a moment that already changes.

You do not certify global pacing — the Director reconciles all layers. Your job is to place your layer sensibly within the budget and **report the change timestamps you add**.

---

## 2. Your tools

### A. `generate_image` — Nano Banana (Gemini Image)
Net-new image generation: illustrations, visual metaphors, designed infographics, conceptual scenes, stylized backgrounds.
- **Never use for:** real logos, real footage, screenshots of real pages/apps, or charts whose numbers must be accurate.

### B. retrieval toolset (fetches things that already exist)
- `fetch_logo(domain, variant, theme, format)` — official brand/org logo by domain.
- `capture_screenshot(url, selector?, block_ads, hide_cookie_banners, full_page?)` — clean image of a real page, article, tweet, or app UI.
- `search_stock_footage(query, min_resolution, orientation)` — real B-roll clips (royalty-free / CC0).
- `extract_article(url)` — `{ headline, source, published, key_facts[], quote? }` for sourcing real data.

### C. (handoff) Remotion — the Director composites your layer
You don't call Remotion. You return placement/animation intent in your shot list, expressed in `brand_kit` motion tokens, and the Director assembles it.

---

## 3. Core principle — generate vs retrieve

> **Generate when the visual is allowed to be invented. Retrieve when it must be real.**

If a wrong or fabricated version would mislead the viewer or misrepresent a real entity → retrieve. Otherwise → generate. When unsure, retrieve.

---

## 4. Reference-type → tool routing

| Reference in transcript | Real? | Tool |
|---|---|---|
| Named brand / company / university (logo) | Yes | `fetch_logo` |
| News article / cited source | Yes | `capture_screenshot`, or `extract_article` + `generate_image` for a designed infographic |
| Stat / number / chart | Yes | `extract_article` / supplied data → return as chart intent (Director renders in Remotion) |
| App, tweet, website, product UI | Yes | `capture_screenshot` |
| Real place / activity / object | Yes | `search_stock_footage` |
| Concept, metaphor, abstract idea | No | `generate_image` |
| Designed infographic | Data real, design invented | `extract_article` (data) → `generate_image` (design) |
| Quote, list, definition, label | No | native text intent (Director renders) |

Specifics: always fetch real logos by domain (never generate them). For articles, prefer a real screenshot for proof or an `extract_article`-sourced infographic for explanation — numbers come only from `extract_article`, never the image model, and the source is attributed. Honor footage licensing and surface required attributions in your output.

---

## 5. Procedure

1. **Segment** the transcript into beats.
2. **Flag reference moments** — entity named, source cited, number stated, something concrete/visual described, or a cut to cover.
3. **Classify and route** each (§4); retrieve before you generate.
4. **Local pacing pass:** within `pacing_budget`, ensure your layer doesn't leave an obvious static stretch where you're the natural illustrator — but do **not** add inserts where `timeline_context` already has a change, and do not breach `min_change_interval_seconds`. Leave true gap-filling punch-ins to the Director.
5. **Style to `brand_kit`** — every asset uses brand tokens; placements stay clear of safe zones, the face, and the caption band.
6. **Emit** the shot list (§6), including the `contributed_change` timestamp for each shot.

---

## 6. Output contract

Return **only** a single valid JSON object:

```json
{
  "shots": [
    {
      "shot_id": 1,
      "start": "00:03.0", "end": "00:06.0",
      "contributed_change": "00:03.0",
      "trigger": "speaker says 'a Harvard study found'",
      "reference_type": "entity_logo",
      "source": "retrieve",
      "tool": "fetch_logo",
      "tool_input": { "domain": "harvard.edu", "variant": "logo", "theme": "auto", "format": "svg" },
      "asset_ref": "logo_harvard",
      "placement": "upper-third card (brand_kit.logo_treatment)",
      "animation": "fade + punch-in (brand_kit.motion.punch_in_range)",
      "rationale": "Real org named; fetch official mark, never generate."
    }
  ],
  "contributed_changes": ["00:03.0", "00:07.5", "..."],
  "notes": "Licensing attributions or flags for the Director."
}
```

Rules:
- `reference_type` ∈ `entity_logo`, `news_source`, `data_stat`, `app_screenshot`, `real_footage`, `concept`, `infographic`, `text_overlay`.
- `source` ∈ `retrieve`, `generate`, `native`, `both`.
- Express every `placement`/`animation` in `brand_kit` tokens — do not hardcode fonts, colors, or dimensions.
- Populate `contributed_changes` so the Director can reconcile global pacing.

---

## 7. Guardrails

- **Never generate a logo, real footage, or a chart from invented data.** Route to the retriever.
- **No misrepresentation:** don't imply endorsement with a real logo; attribute cited articles; don't alter screenshot content.
- **Stay in your lane:** don't redefine the brand kit, don't certify global pacing, don't assemble the final video.
- **Respect injected constraints:** `brand_kit`, `pacing_budget`, and `timeline_context` are authoritative.
- If a moment is ambiguous between generate and retrieve, **retrieve**.
- Output nothing except the JSON object in §6.
"""


class GenerateBrollAgent:
    """Runs a tool-call loop to generate b-roll image and video assets.

    When ``stat_viz_renderer`` is supplied, five animated stat-viz tools (render_counter, render_bar,
    render_gauge, render_before_after, render_ratio) are added to the tool list. When omitted the
    agent operates in image-only mode and the render_* tools are absent from the schema offered to
    the model.
    """

    def __init__(
        self,
        client: ModelClient,
        creator: NanoBananaCreator,
        stat_viz_renderer: StatVizRenderer | None = None,
        style_brief: StyleBrief | None = None,
    ) -> None:
        self._client = client
        self._creator = creator
        self._stat_viz_renderer = stat_viz_renderer
        self._style_brief = style_brief or DEFAULT_STYLE_BRIEF
        self._tools = (
            [_GENERATE_IMAGE_TOOL] + _STAT_VIZ_TOOLS
            if stat_viz_renderer is not None
            else [_GENERATE_IMAGE_TOOL]
        )

    def run(
        self,
        manifest: Manifest,
        brief: str,
        platform: str,
        ideal_cuts_plan: str,
        *,
        dest: Path,
        brand_kit_tokens: dict | None = None,
        creative_direction: str = "",
        director_guidance: str = "",
    ) -> GeneratedBroll:
        dest.mkdir(parents=True, exist_ok=True)
        opening = _build_user_message(
            manifest, brief, platform, ideal_cuts_plan, brand_kit_tokens,
            creative_direction=creative_direction,
            director_guidance=director_guidance,
        )
        history: list[HistoryItem] = [UserMessage(opening)]
        narration_parts: list[str] = []
        slots: list[GeneratedSlot] = []
        n_fail = 0
        ops = 0
        model = getattr(self._client, "model", "unknown") or "unknown"
        turn = 0
        log.get().model_call("generate-broll plan", model)

        with tracing.agent_span(
            "generate-broll-agent",
            input_summary={"platform": platform, "duration_s": manifest.duration},
        ):
            while ops < _MAX_OPS:
                turn += 1
                last_user_text = history[-1].text if isinstance(history[-1], UserMessage) else ""
                with tracing.model_generation(
                    f"generate-broll-turn-{turn}",
                    system=_SYSTEM_PROMPT,
                    user_message=last_user_text[:500],
                    model=model,
                ):
                    assistant: AssistantTurn = self._client.next_turn(
                        system=_SYSTEM_PROMPT, history=history, tools=self._tools
                    )
                tracing.update_generation_output(
                    assistant.text,
                    tool_calls=[tc.name for tc in assistant.tool_calls],
                )
                history.append(assistant)
                if assistant.text:
                    narration_parts.append(assistant.text)
                if not assistant.tool_calls:
                    break

                n_img = sum(1 for tc in assistant.tool_calls if tc.name == "generate_image")
                n_vid = sum(1 for tc in assistant.tool_calls if tc.name in _STAT_VIZ_TOOL_NAMES)
                if n_img or n_vid:
                    log.get().generate_broll_slots(n_img, n_vid)

                prev_len = len(slots)
                results = self._dispatch_parallel(assistant.tool_calls, dest, slots)
                n_fail += (len(assistant.tool_calls) - (len(slots) - prev_len))
                history.append(ToolResultsMessage(tuple(results)))
                ops += len(assistant.tool_calls)

            tracing.update_agent_output({"image_slots": len(slots)})
            log.get().generate_broll_done(len(slots), n_fail)

        return GeneratedBroll(
            plan_text="\n\n".join(narration_parts),
            slots=tuple(slots),
        )

    def _dispatch_parallel(
        self,
        calls: tuple[ToolCall, ...],
        dest: Path,
        slots: list[GeneratedSlot],
    ) -> list[ToolResult]:
        """Dispatch all tool calls in this turn concurrently; collect results in call order."""
        results: list[ToolResult | None] = [None] * len(calls)

        def _run(idx: int, call: ToolCall) -> None:
            result, slot = self._dispatch_one(call, dest)
            results[idx] = result
            if slot is not None:
                slots.append(slot)

        with concurrent.futures.ThreadPoolExecutor() as pool:
            futures = [pool.submit(_run, i, call) for i, call in enumerate(calls)]
            concurrent.futures.wait(futures)

        return [r for r in results if r is not None]

    def _dispatch_one(
        self, call: ToolCall, dest: Path
    ) -> tuple[ToolResult, GeneratedSlot | None]:
        slot_index = int(call.args.get("slot", 0))
        prompt = str(call.args.get("prompt", ""))
        aspect_ratio = str(call.args.get("aspect_ratio", "9:16"))

        if call.name == "generate_image":
            out = dest / f"slot_{slot_index:03d}_{uuid.uuid4().hex[:6]}.png"
            try:
                self._creator.create_image(
                    prompt=prompt, out_path=out, aspect_ratio=aspect_ratio
                )
                slot = GeneratedSlot(
                    slot_index=slot_index, kind="image", path=out, prompt=prompt
                )
                log.get().generate_broll_slot(slot_index, "image", True, prompt)
                return ToolResult(call.id, text=f"image saved: {out}"), slot
            except Exception as exc:
                log.get().generate_broll_slot(slot_index, "image", False, str(exc))
                return ToolResult(call.id, text=f"generate_image failed: {exc}"), None

        if call.name == "generate_video":
            duration = float(call.args.get("duration_seconds", 5))
            out = dest / f"slot_{slot_index:03d}_{uuid.uuid4().hex[:6]}.mp4"
            try:
                self._creator.create_video(
                    prompt=prompt,
                    out_path=out,
                    aspect_ratio=aspect_ratio,
                    duration=duration,
                )
                slot = GeneratedSlot(
                    slot_index=slot_index, kind="video", path=out, prompt=prompt
                )
                log.get().generate_broll_slot(slot_index, "video", True, prompt)
                return ToolResult(call.id, text=f"video saved: {out}"), slot
            except Exception as exc:
                log.get().generate_broll_slot(slot_index, "video", False, str(exc))
                return ToolResult(call.id, text=f"generate_video failed: {exc}"), None

        if call.name in _STAT_VIZ_TOOL_NAMES and self._stat_viz_renderer is not None:
            format_name = call.name.removeprefix("render_")
            data = {k: v for k, v in call.args.items() if k != "slot"}
            out = dest / f"slot_{slot_index:03d}_{uuid.uuid4().hex[:6]}.mp4"
            try:
                self._stat_viz_renderer.render(
                    format_name,  # type: ignore[arg-type]
                    data,
                    self._style_brief,
                    out,
                )
                slot = GeneratedSlot(
                    slot_index=slot_index,
                    kind="video",
                    path=out,
                    prompt=f"{call.name}({data})",
                )
                log.get().generate_broll_slot(slot_index, "video", True, call.name)
                return ToolResult(call.id, text=f"clip saved: {out}"), slot
            except Exception as exc:
                log.get().generate_broll_slot(slot_index, "video", False, str(exc))
                return ToolResult(call.id, text=f"{call.name} failed: {exc}"), None

        return ToolResult(call.id, text=f"unknown tool: {call.name!r}"), None


def _load_nanobanana_styles() -> str:
    """Return a compact style menu from brand-kit/nanobanana_styles.json, or '' if absent."""
    import json as _json
    from pathlib import Path as _Path
    styles_path = _Path(__file__).parent.parent.parent.parent / "brand-kit" / "nanobanana_styles.json"
    if not styles_path.exists():
        return ""
    try:
        data = _json.loads(styles_path.read_text(encoding="utf-8"))
        lines = ["## Nano Banana Image Styles (reference by id in your prompts)"]
        lines.append("Append the style's `prompt` text to your generate_image prompt to activate it.")
        for cat in data.get("categories", []):
            lines.append(f"\n### {cat['id']}. {cat['name']}")
            for s in cat.get("styles", []):
                lines.append(f"  {s['id']} — **{s['name']}**: {s['description']}")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_user_message(
    manifest: Manifest,
    brief: str,
    platform: str,
    ideal_cuts_plan: str,
    brand_kit_tokens: dict | None = None,
    *,
    creative_direction: str = "",
    director_guidance: str = "",
) -> str:
    import json as _json

    lines = [
        f"Platform: {platform}",
        f"Video length: {manifest.duration:.2f}s",
        "",
        f"Speaker context / brief: {brief}",
    ]
    if creative_direction:
        lines += ["", "## Creative Direction (use this to inform every asset you generate)", creative_direction]
    if director_guidance:
        lines += ["", "## Director's Focus for This Dispatch", director_guidance]
    if brand_kit_tokens:
        lines += ["", "## Brand Kit Tokens (style all generated assets to these)", _json.dumps(brand_kit_tokens, indent=2)]
    nb_styles = _load_nanobanana_styles()
    if nb_styles:
        lines += ["", nb_styles]
    lines += [
        "",
        "## IdealCuts Plan",
        ideal_cuts_plan,
        "",
        "## Assets Already Available",
    ]
    for asset in manifest.assets:
        dur = f" {asset.duration:.2f}s" if asset.duration is not None else ""
        desc = f" — {asset.description}" if asset.description else ""
        lines.append(f"  {asset.id} · {asset.type}{dur}{desc}")

    lines += ["", "## Transcript (word-timed)"]
    for word in manifest.transcript.words:
        lines.append(f"  {word.start:.2f}s  {word.text}")

    lines += [
        "",
        "Output the full GENERATEBROLL PLAN first, then execute all generations using your tools.",
    ]
    return "\n".join(lines)
