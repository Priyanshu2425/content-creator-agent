// The `generic` caption renderer: the original karaoke painter that pill / word-bold / kinetic all
// configure (ADR 0010). Extracted verbatim from the former inline TextLayerView so the three
// migrated styles render identically. Captions sit in the lower third, centered, painted from the
// layer's params. A kinetic caption's pop-in rides the same opacity/transform tracks the media layer
// uses, so the shared keyframe sampler -- not per-style code -- drives the animation.

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { sample } from "../sampler";
import type { TextStyle } from "../types";
import type { CaptionRendererProps } from "./types";

export const GenericCaption: React.FC<CaptionRendererProps> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const opacity = sample(layer.opacity, frame, fps, 1);
  const scale = sample(layer.transform?.scale, frame, fps, 1);
  // Dispatched only for generic styles (pill/word-bold/kinetic), so params are always TextStyle
  // (the registry guarantees the id→param-schema match).
  const p = layer.params as TextStyle;
  const timeS = frame / fps; // absolute seconds, for matching a run's spoken window
  // Karaoke when any run carries timing: render one line of word-spans and highlight the word
  // whose [start, end] window contains the current time. Otherwise render the joined line.
  const karaoke = layer.runs.some((run) => run.start != null);
  const body = karaoke ? (
    layer.runs.map((run, i) => {
      const active =
        run.start != null && run.end != null && timeS >= run.start && timeS < run.end;
      const highlight = active && p.highlight_color ? p.highlight_color : p.color;
      return (
        <span
          key={i}
          style={{
            display: "inline-block",
            margin: "0 0.16em",
            color: highlight,
            transform: active ? "scale(1.14)" : "scale(1)",
            textShadow: active ? "0 0 18px rgba(0,0,0,0.45)" : undefined,
          }}
        >
          {run.text}
        </span>
      );
    })
  ) : (
    <>{layer.runs.map((run) => run.text).join(" ")}</>
  );
  return (
    <AbsoluteFill
      style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: "20%" }}
    >
      <div
        style={{
          opacity,
          transform: `scale(${scale})`,
          maxWidth: "82%",
          textAlign: "center",
          fontFamily: "Arial, Helvetica, sans-serif",
          fontSize: p.font_size,
          fontWeight: p.font_weight,
          lineHeight: 1.15,
          color: p.color,
          background: p.background ?? "transparent",
          borderRadius: p.border_radius,
          padding: `${p.padding_y}px ${p.padding_x}px`,
        }}
      >
        {body}
      </div>
    </AbsoluteFill>
  );
};
