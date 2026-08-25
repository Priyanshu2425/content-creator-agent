// The `highlight-box` caption renderer (ADR 0010): the first net-new caption visual beyond the
// generic karaoke look. Ported from the seed `HighlightCaptions` template, word-reveal only -- the
// seed's handwritten annotation + SVG arrow are dropped (not transcript-synced, so not a caption).
//
// Each word wraps in its own colored highlighter box, given a small deterministic rotation jitter,
// and springs in with a per-word pop as its spoken window opens. Unlike the generic renderer the pop
// is owned here (driven by each run's [start,end] window), not by the layer opacity/scale tracks --
// so this style's layer carries no animation tracks (HighlightBoxStyle.compile emits a flat opacity
// and no transform). The renderer owns its own grouping/wrapping/animation and reads only its typed
// params; it does not reach into brand-kit tokens (deferred per ADR 0010).

import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { sample } from "../sampler";
import type { HighlightBoxStyle } from "../types";
import type { CaptionRendererProps } from "./types";

// A small stable per-word jitter in [-1, 1], deterministic on the word index so a box does not
// twitch frame to frame (no Math.random in a render). Cheap hash of the index.
function jitterUnit(index: number): number {
  const x = Math.sin((index + 1) * 12.9898) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1; // fract(x) in [0,1) → [-1,1)
}

export const HighlightCaptions: React.FC<CaptionRendererProps> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const layerOpacity = sample(layer.opacity, frame, fps, 1);
  const p = layer.params as HighlightBoxStyle;
  const timeS = frame / fps; // absolute seconds, for matching a run's spoken window
  const colors = p.box_colors.length > 0 ? p.box_colors : ["#FFE14D"];

  return (
    <AbsoluteFill
      style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: "20%" }}
    >
      <div
        style={{
          opacity: layerOpacity,
          maxWidth: "84%",
          display: "flex",
          flexWrap: "wrap",
          gap: "0.28em 0.22em",
          justifyContent: "center",
          fontFamily: "Arial, Helvetica, sans-serif",
          fontSize: p.font_size,
          fontWeight: p.font_weight,
          lineHeight: 1.25,
        }}
      >
        {layer.runs.map((run, i) => {
          // A word is "revealed" once its spoken window opens; before that it stays hidden so the
          // boxes pop in one at a time with the voiceover.
          const wordStart = run.start ?? layer.start;
          const startFrame = Math.round((wordStart - from / fps) * fps);
          const revealed = run.start == null || timeS >= run.start;
          const pop =
            p.pop_seconds > 0
              ? spring({
                  frame: frame - from - startFrame,
                  fps,
                  config: { damping: 12, stiffness: 200, mass: 0.6 },
                  durationInFrames: Math.max(1, Math.round(p.pop_seconds * fps)),
                })
              : 1;
          const scale = revealed
            ? p.pop_start_scale + (1 - p.pop_start_scale) * pop
            : p.pop_start_scale;
          const rot = jitterUnit(i) * p.rotation_jitter_deg;
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                opacity: revealed ? 1 : 0,
                transform: `rotate(${rot}deg) scale(${scale})`,
                color: p.text_color,
                background: colors[i % colors.length],
                borderRadius: p.box_radius,
                padding: `${p.padding_y}px ${p.padding_x}px`,
              }}
            >
              {run.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
