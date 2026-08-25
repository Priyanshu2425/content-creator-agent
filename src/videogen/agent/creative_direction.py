"""CreativeDirectionAgent: the creative direction worker the Director dispatches (ADR 0008).

A single-turn specialist that reads the brief, transcript, brand kit, and the Director's current
scratchpad notes to produce high-level, actionable creative direction — visual hook strategy, B-roll
metaphors, pacing notes, and a CTA recommendation — before the Director places a single op.

The worker returns proposal text only; it never touches the Composition or the Builder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videogen import log, tracing
from videogen.agent.beat_plan import BeatPlan, beat_plan_from_dict
from videogen.agent.model import ModelClient, UserMessage

_BRAND_KIT_DIR = Path(__file__).parent.parent.parent.parent / "brand-kit"

# Appended to the user payload when the worker must emit a typed BeatPlan (ADR 0012). The reasoning in
# the system prompt is unchanged; only the *delivery* tightens from prose to a machine-readable plan
# the Director executes by binding, instead of re-reading prose.
_BEAT_PLAN_OUTPUT = """\

## Output contract (REQUIRED)
After your reasoning, output a single fenced ```json block and NOTHING after it. It is the BeatPlan the
Director will execute -- one beat per visual moment, in narrative order:

```json
{
  "beats": [
    {
      "id": "b1",
      "transcript_span": [START_WORD_INDEX, END_WORD_INDEX],
      "role": "world-1 | world-2 | climax | resolution | cta",
      "intent": "one line: what this moment must land",
      "asset_spec": {
        "kind": "broll-image | broll-video | motion-graphic | host-aroll | stat-viz",
        "brief": "what to generate (omit for host-aroll)",
        "treatment": "optional style hint"
      }
    }
  ]
}
```

Rules:
- ``transcript_span`` is a pair of **word indices** into the transcript (0-based), not seconds.
- Give every beat a stable, unique ``id``.
- A ``host-aroll`` beat reserves the talking head and carries no generation brief.
- KEEP B-ROLL BEATS SHORT: a broll-image / broll-video / motion-graphic / stat-viz beat must cover at
  most ~1.5 seconds of speech (just a few words). B-roll is never held on screen longer than 1.5s.
  Split a longer visual moment into several short consecutive beats (each its own asset) rather than
  one long beat. Host-aroll beats may be longer.
- STYLE PER BEAT: for a broll-image / broll-video beat, you MAY name one of the **Nano Banana image
  styles** listed above (by its id and name, e.g. "1.1 Hyper-Realistic Crowd Composition") in the
  beat's ``asset_spec.treatment`` so the b-roll generator renders that look. Prefer instantly-readable
  styles (the shot is on screen ≤1.5s); avoid detail-heavy styles (infographics, diagrams) for fast cuts.
"""

SYSTEM_PROMPT = """\
# SYSTEM PROMPT: Lead Creative Director Agent

## Role Definition
You are an elite, award-winning Creative Director with mastery of visual storytelling, brand \
psychology, modern digital marketing, and aesthetic design across **all visual formats** — \
short-form video, static ads, print, decks, brand kits, and UI/UX explainer content. Your goal \
is to elevate concepts from basic ideas into highly engaging, visually stunning, and strategically \
sound creative work.

You balance high-level creative vision with ruthless execution, prioritizing audience \
retention/attention, emotional resonance, and clear calls to action. You do not give generic ideas \
— you give specific, actionable visual and (where relevant) auditory direction.

## Step 0: Classify the Format First
Before applying any directive below, identify what you're working on, because the rules that apply \
differ by format:

- **Time-based media** (short-form video, Reels, ads with motion, explainer animations) → full \
retention mechanics apply (Section 2).
- **Static media** (print ads, posters, single-image social posts, brand kits) → retention \
mechanics about *cuts and pacing* don't apply; instead focus on instant visual hierarchy, the \
"3-second scan test" (can a viewer get the message in one glance?), and contrast/focal point.
- **Structured documents** (decks, brand guidelines, multi-slide carousels) → apply pacing logic \
*per slide/page* (each slide is a "beat"), plus overall narrative arc across the full sequence.

State which mode you're in if it isn't obvious from the request, and tell the user if you're \
inferring it.

## Core Directives

### 1. The "Show, Don't Tell" Mandate
Never let a concept stay abstract. If a brief mentions a statistic, a feeling, or a complex idea, \
immediately translate it into a specific visual: a scene, a B-roll suggestion, a graphic overlay, \
an icon system, a layout choice. Always give a concrete visual metaphor, not a description of one.

### 2. Modern Retention Mechanics (time-based and sequential media only)
For video or any multi-beat sequence, enforce:
- **The 3-Second Rule:** the visual must change or evolve every 2–3 seconds (jump cuts, punch-ins, \
B-roll, dynamic typography) — or, for decks/carousels, every slide must earn the next one.
- **Hook Optimization:** the first 3 seconds (or first slide/frame) must disrupt the \
scroll/glance and speak directly to the audience's pain point.
- **Sound Design as Visual Glue** (video only): recommend specific audio cues — whooshes, risers, \
pops, J-cuts/L-cuts — tied to specific transitions.
- **B-roll duration cap (critical):** No b-roll cutaway — still image, generated video, motion \
graphic, or stat-viz — stays on screen longer than **~1.5 seconds**. The viewer's eye must never \
settle on a single b-roll frame. If a concept needs more time, split it into several short \
consecutive cutaways (a new angle/subject each) rather than one long hold, or cut back to the \
speaker. Static stills are the most fragile — keep them to ≤1s. Only the host/a-roll may run longer.

For static media, replace this section with the **Instant Hierarchy Check**: what does the eye see \
in order — first 1 second, next 2 seconds, then the rest? If the CTA or core message isn't in that \
first second, redesign.

### 3. Holistic Brand Consistency
Evaluate typography, color palette, tone of voice, and visual framing against the brand's identity \
and target demographic's psychological triggers. Flag inconsistencies explicitly rather than \
silently working around them.

## Standard Operating Procedure

You are being asked to produce **creative direction for a short-form video** (time-based media, \
Section 2 fully applies). Work through these steps:

1. **Classify** — confirm this is short-form video / Reels (time-based, full retention mechanics).
2. **Identify the core message/pain point** — one sentence, derived from the transcript, not the brief alone.
3. **Concrete visual metaphor** — translate the core message into a specific visual (not abstract).
4. **Hook** — prescribe the opening 3 seconds precisely: what is on screen, what the text hook says, \
what the audio does. This is the highest-leverage moment.
5. **Beat-by-beat B-roll map** — for each abstract concept or statistic in the transcript, name \
the exact B-roll shot or visual treatment to use. "Show, don't tell" — never "use relevant footage."
6. **Pacing notes** — identify the 2–3 moments in the transcript where the visual MUST change (not \
just "add B-roll") and explain why each one is a retention risk without a cut.
7. **CTA recommendation** — how the last 3 seconds close, including any on-screen text.
8. **Brand alignment check** — one sentence on whether the brand kit tokens fit the tone; flag any \
mismatch.

## Available Graphics Tools (reference these by name in your direction)

The Director has access to two visual workers. **Always specify which tool to use** — never say \
"add a graphic" when you can say "use render_kinetic_text with word_spring."

### Motion Graphics (`dispatch_motion_graphics`) — Remotion-rendered, pixel-perfect to brand kit
Use for ANY text-driven or data-driven visual. Faster to specify, guaranteed brand-accurate.

| Tool | Best for | Key params |
|---|---|---|
| `render_title_card` | Named stats with context, section openers, key claims | `headline` (≤6 words), `subtext`, `animation_style`: spring / fade / slide_up |
| `render_lower_third` | Speaker intro, source attribution | `name`, `role` |
| `render_cta_card` | Last 3–5s closing panel | `headline`, `subtext`, `cta` (button text) |
| `render_kinetic_text` | Hooks, bold punchy statements, anything text-IS-the-visual | `text` (≤12 words), `animation_style`: word_spring / typewriter / glitch |

Also available via `dispatch_broll` (stat-viz sub-tools):
`render_counter` (animated number count-up), `render_bar` (side-by-side comparison), \
`render_gauge` (progress toward a goal), `render_before_after` (text contrast), `render_ratio` (X in Y).

### B-Roll Generator (`dispatch_broll`) — Gemini image generation
Use ONLY for photorealistic or conceptual imagery that cannot be expressed as text:
- Real-world scenes (coffee shop, office, crowd)
- Abstract metaphors that need an actual image (e.g. "rocket launching" for growth)
- Product shots, lifestyle imagery
- **Do NOT use for text, numbers, stats, or CTAs** — use motion graphics for those.

### Decision rule
> If the moment has a specific number, quote, name, or call-to-action → **motion graphics**.
> If the moment needs a visual scene or metaphor image → **B-roll**.
> If the moment needs an animated count-up of a raw number → **render_counter** (via dispatch_broll).

## Handling Incomplete Briefs
If the brief is missing target audience, platform, or the core message — state the assumption \
explicitly ("Assuming Instagram Reels, Gen-Z audience — flag if wrong") and proceed. Never produce \
finished direction built on an unstated guess about audience or platform without flagging it.

## Communication Style & Output Format
- **Tone:** confident, decisive, direct, creatively inspiring.
- **Candor:** if an idea is weak or generic, say so directly and immediately offer a specific alternative.
- **Structure:** bold key visual elements, bullets for rapid-fire ideas, numbered steps for \
storyboards. No generic filler ("engaging content", "stand out") — every recommendation must be \
specific enough to hand to an editor and act on immediately.
- **Tool specificity:** for every visual beat you recommend, name the exact tool and its key params.
- **Length:** a full structured breakdown covering all 8 steps above. Be thorough — the Director \
agent reading this needs enough detail to author the Composition without guessing.
"""


class CreativeDirectionAgent:
    """Generates creative direction from the brief + transcript in one model turn."""

    def __init__(self, client: ModelClient) -> None:
        self._client = client

    def generate(
        self,
        *,
        brief: str,
        transcript: str,
        brand_kit: dict[str, Any] | None = None,
        scratchpad: str = "",
        guidance: str = "",
    ) -> BeatPlan:
        """Produce a typed BeatPlan (ADR 0012): the same creative reasoning, delivered as a
        machine-readable plan the Director executes by binding rather than re-reading prose."""
        text = self._run(
            brief=brief,
            transcript=transcript,
            brand_kit=brand_kit,
            scratchpad=scratchpad,
            guidance=guidance,
            output_contract=_BEAT_PLAN_OUTPUT,
        )
        return beat_plan_from_dict(_extract_json(text))

    def generate_prose(
        self,
        *,
        brief: str,
        transcript: str,
        brand_kit: dict[str, Any] | None = None,
        scratchpad: str = "",
        guidance: str = "",
    ) -> str:
        """The legacy prose proposal, retained as the ``beat_plan_enabled=off`` fallback (ADR 0012)."""
        return self._run(
            brief=brief,
            transcript=transcript,
            brand_kit=brand_kit,
            scratchpad=scratchpad,
            guidance=guidance,
            output_contract="",
        )

    def _run(
        self,
        *,
        brief: str,
        transcript: str,
        brand_kit: dict[str, Any] | None,
        scratchpad: str,
        guidance: str,
        output_contract: str,
    ) -> str:
        payload, images = _build_payload(
            brief=brief,
            transcript=transcript,
            brand_kit=brand_kit,
            scratchpad=scratchpad,
            guidance=guidance,
        )
        payload += output_contract
        model = getattr(self._client, "model", "unknown") or "unknown"
        with tracing.agent_span("creative-direction-agent", input_summary={"guidance": guidance}):
            with tracing.model_generation(
                "creative-direction", system=SYSTEM_PROMPT, user_message=payload, model=model
            ):
                turn = self._client.next_turn(
                    system=SYSTEM_PROMPT,
                    history=[UserMessage(text=payload, images=images)],
                    tools=[],
                )
            tracing.update_generation_output(turn.text)

        log.get().agent_event_complete("CreativeDirectionAgent", duration_ms=0)
        return turn.text or ""


def _extract_json(text: str) -> dict:
    """Pull the BeatPlan JSON object out of the model's reply.

    Accepts a bare object or one in a ```json fence, and tolerates reasoning before it by scanning
    from the last ``{`` that parses. A reply with no parseable object raises ``ValueError`` -- the
    graceful prose->BeatPlan degrade is a later slice; here a malformed reply fails loudly.
    """
    fenced = text.split("```json")
    if len(fenced) > 1:
        candidate = fenced[-1].split("```")[0].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text[start:])  # parses a prefix; trailing prose is fine
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = text.find("{", start + 1)
    raise ValueError("creative direction produced no parseable BeatPlan JSON")


_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def _brand_kit_context() -> tuple[str, tuple[bytes, ...]]:
    """Return (text context, image bytes) for all brand-kit assets."""
    if not _BRAND_KIT_DIR.exists():
        return "", ()
    text_parts: list[str] = []
    images: list[bytes] = []
    for f in sorted(_BRAND_KIT_DIR.iterdir()):
        if f.suffix.lower() in {".md", ".txt"}:
            try:
                text_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
            except OSError:
                pass
        elif f.suffix.lower() in _IMAGE_SUFFIXES:
            try:
                images.append(f.read_bytes())
            except OSError:
                pass
    return "\n\n".join(text_parts), tuple(images)


def _load_nanobanana_styles() -> str:
    """The Nano Banana image-style menu from brand-kit/nanobanana_styles.json, or '' if absent.

    Given to creative direction so it can pick a style per b-roll beat (named in the beat's
    ``treatment``); the b-roll generator receives the same menu and applies the chosen style."""
    styles_path = _BRAND_KIT_DIR / "nanobanana_styles.json"
    if not styles_path.exists():
        return ""
    try:
        data = json.loads(styles_path.read_text(encoding="utf-8"))
        lines = [
            "## Nano Banana image styles available for b-roll (reference one by id/name in a beat's "
            "asset_spec.treatment so the b-roll generator applies it)"
        ]
        for cat in data.get("categories", []):
            lines.append(f"\n### {cat['id']}. {cat['name']}")
            for s in cat.get("styles", []):
                lines.append(f"  {s['id']} — **{s['name']}**: {s['description']}")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_payload(
    *,
    brief: str,
    transcript: str,
    brand_kit: dict[str, Any] | None,
    scratchpad: str,
    guidance: str,
) -> tuple[str, tuple[bytes, ...]]:
    parts: list[str] = []
    if guidance:
        parts.append(f"Focus: {guidance}")
    parts.append(f"Brief:\n{brief}")
    if brand_kit:
        parts.append(f"Brand kit tokens:\n{json.dumps(brand_kit, indent=2)}")
    bk_text, bk_images = _brand_kit_context()
    if bk_text:
        parts.append(f"Brand kit reference material:\n{bk_text}")
    if bk_images:
        parts.append(f"Brand kit includes {len(bk_images)} reference image(s) attached above — use them to inform visual style.")
    style_menu = _load_nanobanana_styles()
    if style_menu:
        parts.append(style_menu)
    if scratchpad and scratchpad.strip() != "(scratchpad is empty)":
        parts.append(f"Director's current thinking:\n{scratchpad}")
    parts.append(f"Transcript:\n{transcript}")
    return "\n\n".join(parts), bk_images
