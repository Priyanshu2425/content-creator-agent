// The `title` text-layer renderer (ADR 0010). NOT a caption: the text-hook overlay emits a `text`
// layer with style "title" (a static headline pinned to the upper third), sharing the text-layer
// kind and the registry dispatch but not the caption semantics. Registered so the one dispatch path
// covers it -- the former isTitle branch of the inline TextLayerView.

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { sample } from "../sampler";
import type { TextStyle } from "../types";
import { THE_BOLD_FONT } from "./the-bold-font";
import type { CaptionRendererProps } from "./types";

export const TitleCaption: React.FC<CaptionRendererProps> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const opacity = sample(layer.opacity, frame, fps, 1);
  const scale = sample(layer.transform?.scale, frame, fps, 1);
  // Placement is baked into the IR as a vertical translate (title/ir.py): the layer is centred by
  // default and lifted into the upper third by a negative translate_y for "upper-third" placement.
  const tx = sample(layer.transform?.translate_x, frame, fps, 0);
  const ty = sample(layer.transform?.translate_y, frame, fps, 0);
  // The title renderer paints from the generic TextStyle params (style id "title").
  const p = layer.params as TextStyle;
  // A title is a single static run; render the joined line (no karaoke timing).
  const body = <>{layer.runs.map((run) => run.text).join(" ")}</>;
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          opacity,
          transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
          maxWidth: "82%",
          textAlign: "center",
          // Match the TikTok transcript captions: same loaded display face, same fallback stack.
          fontFamily: `"${THE_BOLD_FONT}", Arial, Helvetica, sans-serif`,
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
