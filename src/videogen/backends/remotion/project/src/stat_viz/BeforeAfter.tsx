import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatVizBeforeAfterProps } from "./types";

export const StatVizBeforeAfter: React.FC<StatVizBeforeAfterProps> = ({
  label_a,
  value_a,
  label_b,
  value_b,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const afterStart = Math.floor(durationInFrames * 0.4);

  const opacityBefore = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const opacityArrow = interpolate(frame, [10, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const opacityAfter = interpolate(frame, [afterStart, afterStart + 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
      }}
    >
      {/* Before panel */}
      <div style={{ opacity: opacityBefore, textAlign: "center" }}>
        <div
          style={{
            color: primary,
            fontSize: 48,
            opacity: 0.6,
          }}
        >
          {label_a}
        </div>
        <div
          style={{
            color: primary,
            fontSize: 110,
            fontWeight: 700,
            marginTop: 16,
          }}
        >
          {value_a}
        </div>
      </div>

      {/* Arrow */}
      <div
        style={{
          opacity: opacityArrow,
          color: accent,
          fontSize: 90,
          marginTop: 24,
          marginBottom: 24,
        }}
      >
        ↓
      </div>

      {/* After panel */}
      <div style={{ opacity: opacityAfter, textAlign: "center" }}>
        <div
          style={{
            color: accent,
            fontSize: 48,
          }}
        >
          {label_b}
        </div>
        <div
          style={{
            color: accent,
            fontSize: 110,
            fontWeight: 900,
            marginTop: 16,
          }}
        >
          {value_b}
        </div>
      </div>
    </AbsoluteFill>
  );
};
