import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatVizCounterProps } from "./types";

export const StatVizCounter: React.FC<StatVizCounterProps> = ({
  value,
  unit,
  label,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const animatedValue = interpolate(
    frame,
    [0, Math.floor(durationInFrames * 0.8)],
    [0, value],
    { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
  );

  const opacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

  const displayValue =
    value % 1 === 0
      ? Math.round(animatedValue).toString()
      : animatedValue.toFixed(1);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
        opacity,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <span
          style={{
            color: accent,
            fontSize: 220,
            fontWeight: 900,
            lineHeight: 1,
          }}
        >
          {displayValue}
        </span>
        <span
          style={{
            color: accent,
            fontSize: 120,
            fontWeight: 700,
            lineHeight: 1,
          }}
        >
          {unit}
        </span>
      </div>
      <div
        style={{
          color: primary,
          fontSize: 60,
          marginTop: 40,
          opacity: 0.8,
          textAlign: "center",
          maxWidth: 900,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
