"""MotionGraphicsAgent: LLM-generated Remotion compositions for animated text clips.

The LLM (Gemini, vision-capable) receives the brief, transcript, creative direction, brand kit
tokens, and brand kit reference image(s). It generates complete, self-contained Remotion TSX
files — component definition + RemotionRoot composition registration — which Python writes to
disk and renders via `npx remotion render <file> GeneratedMotionGraphic <out_path>`.

No pre-built templates. The LLM owns the full animation, layout, colors, and timing.
Brand kit images are injected as multipart vision content so the model can match the visual style.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from videogen import log, tracing

# ---------------------------------------------------------------------------
# Remotion API cheat-sheet injected into the system prompt
# ---------------------------------------------------------------------------

_REMOTION_CHEATSHEET = """\
## Remotion API (everything you need)

```tsx
import React from 'react';
import { Composition } from 'remotion';
import {
  AbsoluteFill,        // full-canvas positioned container
  useCurrentFrame,     // () => number — current frame index
  useVideoConfig,      // () => { width, height, fps, durationInFrames }
  interpolate,         // (value, inputRange, outputRange, options?) => number
  spring,              // ({ frame, fps, config?, durationInFrames? }) => 0→1
  Sequence,            // <Sequence from={N} durationInFrames={N}> delayed content
} from 'remotion';
```

### Key patterns
```tsx
// Fade in over first 15 frames
const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });

// Spring entrance (0→1, overshoot-free)
const progress = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });
const translateY = interpolate(progress, [0, 1], [60, 0]);

// Fade out last 12 frames
const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0],
  { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

// Delayed sequence (start at frame 20)
<Sequence from={20}><YourComponent /></Sequence>

// Word-by-word spring reveal
const words = text.split(' ');
words.map((word, i) => {
  const delay = Math.floor((i / words.length) * fps * 0.8);
  const p = spring({ frame: frame - delay, fps, config: { damping: 14, stiffness: 130 } });
  return <span style={{ opacity: p, transform: `translateY(${interpolate(p,[0,1],[30,0])}px)` }}>{word} </span>;
})
```

### Required file structure (MUST follow exactly)
```tsx
import React from 'react';
import { Composition } from 'remotion';
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring, Sequence } from 'remotion';

// 1. Your component — no external imports, no staticFile, all styles inline
const MotionGraphic: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  // ... your animation
  return <AbsoluteFill style={{ ... }}>...</AbsoluteFill>;
};

// 2. REQUIRED export — keep composition id exactly "GeneratedMotionGraphic"
export const RemotionRoot: React.FC = () => (
  <Composition
    id="GeneratedMotionGraphic"
    component={MotionGraphic}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={90}
    defaultProps={{}}
  />
);
```

### Constraints
- NO external imports beyond React + remotion (no framer-motion, no gsap, no css files)
- NO `staticFile()` — all assets must be inline (colors, SVG paths as JSX, no image files)
- NO `Math.random()` or `Date.now()` — use frame-based determinism only
- All pixel values for 1080×1920 canvas
- `durationInFrames` = seconds × 30 (e.g. 3s = 90 frames)
- Export must be named `RemotionRoot` with composition id `"GeneratedMotionGraphic"`
"""

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are a motion-graphics engineer for a short-form video pipeline. You generate complete,
self-contained Remotion TypeScript/React compositions that produce animated text clips for
Instagram Reels / TikTok (1080×1920, 30fps).

These clips are cut into a fast edit and shown on screen for **~1.5 seconds at most** — keep each clip
short and punchy (default `duration_s` ≈ 1.5, never more than ~2s), and make the message land
instantly with motion from frame one. A clip that only reads after 2–3s is too slow for this edit.

You will be given:
- The video brief and transcript
- Creative direction (what the clip should communicate)
- Brand kit tokens (colors, fonts, style)
- Brand kit reference image(s) — match this visual aesthetic closely

Your job: call `render_motion_graphic` once per clip you want to produce. Each call includes:
- `code`: a complete, valid TSX file following the structure below
- `duration_s`: clip duration in seconds
- `label`: a one-line description of what this clip shows

Guidelines:
- 3–6 clips per video is typical
- Match brand colors exactly from the tokens provided
- The reference image shows the visual style — replicate its energy, not its content
- Use spring animations for organic motion, interpolate for linear control
- Dark backgrounds read better at small sizes; keep contrast high
- Keep text short: headlines ≤6 words, supporting text ≤12 words
- The last clip should almost always be a CTA card

{_REMOTION_CHEATSHEET}
"""

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_RENDER_TOOL = ToolSpec(
    name="render_motion_graphic",
    description="Generate and render one animated Remotion clip. Call once per clip you want to produce.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Complete self-contained TSX file. Must export RemotionRoot with composition id 'GeneratedMotionGraphic'.",
            },
            "duration_s": {
                "type": "number",
                "description": "Clip duration in seconds (2–6). Sets durationInFrames = duration_s * 30 in your composition.",
            },
            "label": {
                "type": "string",
                "description": "One-line description of what this clip shows (used as asset description).",
            },
        },
        "required": ["code", "duration_s", "label"],
    },
)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratedMgSlot:
    slot_index: int
    path: Path
    label: str
    duration_s: float


@dataclass(frozen=True)
class GeneratedMotionGraphics:
    slots: tuple[GeneratedMgSlot, ...]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MotionGraphicsAgent:
    """Generates animated motion-graphic clips via LLM-authored Remotion code.

    The model (Gemini, vision-capable) writes complete TSX files which are rendered
    via the existing RemotionBackend. Brand kit images are injected as multipart content.
    """

    _MAX_TURNS = 16  # enough for 6 clips + planning turns

    def __init__(
        self,
        client: ModelClient,
        backend: Any | None = None,
    ) -> None:
        self._client = client
        if backend is None:
            from videogen.backends.remotion import RemotionBackend
            backend = RemotionBackend()
        self._backend = backend

    def run(
        self,
        brief: str,
        transcript: str,
        creative_direction: str = "",
        director_guidance: str = "",
        brand_kit: dict[str, Any] | None = None,
        brand_kit_images: tuple[bytes, ...] = (),
        dest: Path = Path("."),
        fps: int = 30,
    ) -> GeneratedMotionGraphics:
        dest.mkdir(parents=True, exist_ok=True)
        opening_text = _build_user_message(
            brief=brief,
            transcript=transcript,
            creative_direction=creative_direction,
            director_guidance=director_guidance,
            brand_kit=brand_kit,
            brand_kit_images=brand_kit_images,
        )
        history: list[HistoryItem] = [UserMessage(text=opening_text, images=brand_kit_images)]
        slots: list[GeneratedMgSlot] = []
        slot_idx = 0

        with tracing.agent_span("motion-graphics-agent", input_summary={"brief": brief[:80]}):
            for _ in range(self._MAX_TURNS):
                turn = self._client.next_turn(
                    system=_SYSTEM_PROMPT,
                    history=history,
                    tools=[_RENDER_TOOL],
                )
                history.append(turn)

                if not turn.tool_calls:
                    break

                results: list[ToolResult] = []
                for call in turn.tool_calls:
                    result, slot = self._render_call(call, dest=dest, slot_idx=slot_idx, fps=fps)
                    results.append(result)
                    if slot:
                        slots.append(slot)
                        slot_idx += 1
                history.append(ToolResultsMessage(tuple(results)))

        return GeneratedMotionGraphics(slots=tuple(slots))

    def _render_call(
        self, call: ToolCall, *, dest: Path, slot_idx: int, fps: int
    ) -> tuple[ToolResult, GeneratedMgSlot | None]:
        code = str(call.args.get("code", ""))
        duration_s = float(call.args.get("duration_s", 3.0))
        label = str(call.args.get("label", f"clip_{slot_idx}"))

        if not code.strip():
            return ToolResult(call.id, text="error: code was empty"), None

        out = dest / f"mg_{slot_idx:03d}_{uuid.uuid4().hex[:6]}.mp4"
        try:
            self._backend.render_generated_clip(code, out)
            slot = GeneratedMgSlot(slot_index=slot_idx, path=out, label=label, duration_s=duration_s)
            log.get().agent_event_complete(f"mg-render:{label[:40]}", duration_ms=0)
            return ToolResult(call.id, text=f"rendered: {out.name} ({duration_s}s)"), slot
        except Exception as exc:
            log.get().agent_event_complete("mg-render:failed", duration_ms=0)
            return ToolResult(call.id, text=f"render failed: {exc}"), None


# ---------------------------------------------------------------------------
# User message builder
# ---------------------------------------------------------------------------

def _build_user_message(
    *,
    brief: str,
    transcript: str,
    creative_direction: str,
    director_guidance: str,
    brand_kit: dict[str, Any] | None,
    brand_kit_images: tuple[bytes, ...],
) -> str:
    parts: list[str] = []
    if director_guidance:
        parts.append(f"Director's focus:\n{director_guidance}")
    parts.append(f"Brief:\n{brief}")
    if brand_kit:
        parts.append(f"Brand kit tokens (use these exact colors and fonts):\n{json.dumps(brand_kit, indent=2)}")
    if brand_kit_images:
        parts.append(
            f"{len(brand_kit_images)} brand kit reference image(s) attached above — "
            "match this visual style, energy, and aesthetic in your compositions."
        )
    if creative_direction:
        parts.append(f"Creative direction (what each clip should communicate):\n{creative_direction}")
    parts.append(f"Transcript:\n{transcript}")
    parts.append(
        "Now generate the motion-graphic clips for this video. "
        "Call render_motion_graphic once per clip. Aim for 3–6 clips total."
    )
    return "\n\n".join(parts)
