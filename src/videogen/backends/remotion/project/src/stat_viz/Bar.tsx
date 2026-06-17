import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatVizBarProps } from "./types";

export const StatVizBar: React.FC<StatVizBarProps> = ({
  label_a,
  value_a,
  label_b,
  value_b,
  unit,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const animEnd = Math.floor(durationInFrames * 0.8);
  const maxValue = Math.max(value_a, value_b);

  const widthA = interpolate(
    frame,
    [0, animEnd],
    [0, (value_a / maxValue) * 100],
    { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
  );

  const widthB = interpolate(
    frame,
    [0, animEnd],
    [0, (value_b / maxValue) * 100],
    { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
  );

  const opacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  const barRow = (
    label: string,
    value: number,
    color: string,
    animatedWidth: number
  ) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ color, fontSize: 44, fontFamily, fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <div
          style={{
            flex: 1,
            height: 80,
            borderRadius: 8,
            backgroundColor: `${color}33`,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${animatedWidth}%`,
              height: "100%",
              backgroundColor: color,
              borderRadius: 8,
            }}
          />
        </div>
        <div
          style={{
            color,
            fontSize: 64,
            fontWeight: 900,
            fontFamily,
            minWidth: 180,
            textAlign: "right",
          }}
        >
          {value}
          {unit}
        </div>
      </div>
    </div>
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "0 80px",
        opacity,
        gap: 80,
      }}
    >
      {barRow(label_a, value_a, primary, widthA)}
      {barRow(label_b, value_b, accent, widthB)}
    </AbsoluteFill>
  );
};
