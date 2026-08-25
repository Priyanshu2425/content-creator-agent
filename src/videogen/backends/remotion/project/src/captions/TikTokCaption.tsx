// The `tiktok` caption renderer (ADR 0010): a port of Remotion's TikTok captions template
// (https://www.remotion.dev/templates/tiktok) into our runs-based caption contract. Heavy text with
// a thick black stroke (`paintOrder: "stroke"`), the whole line popping in (scale + rise) at the
// layer start, and the word being spoken *now* recoloured to the template's bright green with a
// small scale bump. Unlike the generic renderer the enter animation is owned here (a spring driven
// off the layer start), not the layer opacity/scale tracks -- so this style's layer carries none
// (TikTokStyle.compile emits a flat opacity and no transform). The renderer reads only its typed
// params; it does not reach into brand-kit tokens (deferred per ADR 0010).

import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { TikTokStyle } from "../types";
import { THE_BOLD_FONT } from "./the-bold-font";
import type { CaptionRendererProps } from "./types";

export const TikTokCaption: React.FC<CaptionRendererProps> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame
  const timeS = frame / fps; // absolute seconds, for matching a run's spoken window
  const p = layer.params as TikTokStyle;

  // The whole line springs in at the layer start (scale up + rise), mirroring the template's page
  // enter. A relative frame of 0 at the layer's first frame so every caption enters the same way.
  const popFrames = Math.max(1, Math.round((p.pop_seconds > 0 ? p.pop_seconds : 0.2) * fps));
  const enter = spring({
    frame: frame - from,
    fps,
    config: { damping: 200 },
    durationInFrames: popFrames,
  });
  const enterScale = interpolate(enter, [0, 1], [p.pop_start_scale, 1]);
  const enterY = interpolate(enter, [0, 1], [p.pop_translate_y, 0]);

  return (
    <AbsoluteFill
      style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: "20%" }}
    >
      <div
        style={{
          transform: `translateY(${enterY}px) scale(${enterScale})`,
          maxWidth: "84%",
          display: "flex",
          flexWrap: "wrap",
          gap: "0.12em 0.3em",
          justifyContent: "center",
          textAlign: "center",
          fontFamily: `"${THE_BOLD_FONT}", Arial, Helvetica, sans-serif`,
          fontSize: p.font_size,
          fontWeight: p.font_weight,
          lineHeight: 1.1,
          color: p.color,
          WebkitTextStroke: p.stroke_width > 0 ? `${p.stroke_width}px ${p.stroke_color}` : undefined,
          paintOrder: "stroke",
        }}
      >
        {layer.runs.map((run, i) => {
          const active =
            run.start != null && run.end != null && timeS >= run.start && timeS < run.end;
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                whiteSpace: "pre",
                color: active && p.active_color ? p.active_color : p.color,
                transform: active ? "scale(1.06)" : "scale(1)",
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
