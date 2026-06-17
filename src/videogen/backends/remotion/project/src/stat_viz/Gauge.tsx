import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatVizGaugeProps } from "./types";

export const StatVizGauge: React.FC<StatVizGaugeProps> = ({
  value,
  max,
  unit,
  label,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });

  const animatedProgress = interpolate(
    frame,
    [0, Math.floor(durationInFrames * 0.8)],
    [0, value / max],
    { extrapolateRight: "clamp" }
  );

  const radius = 280;
  const strokeWidth = 48;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference * (1 - animatedProgress);

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
      <div style={{ position: "relative", width: 700, height: 700 }}>
        <svg
          width="700"
          height="700"
          viewBox="-350 -350 700 700"
          style={{ display: "block" }}
        >
          {/* Background track */}
          <circle
            r={radius}
            fill="none"
            stroke={primary}
            strokeWidth={strokeWidth}
            opacity={0.2}
          />
          {/* Animated progress arc */}
          <circle
            r={radius}
            fill="none"
            stroke={accent}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            transform="rotate(-90)"
          />
        </svg>
        {/* Centre value text */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            color: accent,
            fontSize: 160,
            fontWeight: 900,
            lineHeight: 1,
            fontFamily,
          }}
        >
          {value}
          {unit}
        </div>
      </div>
      {/* Label */}
      <div
        style={{
          color: primary,
          fontSize: 54,
          marginTop: 32,
          textAlign: "center",
          fontFamily,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
