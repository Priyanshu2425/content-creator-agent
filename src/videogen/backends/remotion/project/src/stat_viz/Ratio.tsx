import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatVizRatioProps } from "./types";

export const StatVizRatio: React.FC<StatVizRatioProps> = ({
  numerator,
  denominator,
  label,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });

  const filledCount = Math.floor(
    interpolate(frame, [0, durationInFrames * 0.8], [0, numerator + 0.99], {
      extrapolateRight: "clamp",
    })
  );

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
          color: accent,
          fontSize: 100,
          fontWeight: 900,
          marginBottom: 60,
          lineHeight: 1,
        }}
      >
        {numerator} in {denominator}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 20,
          justifyContent: "center",
          maxWidth: 900,
        }}
      >
        {Array.from({ length: denominator }, (_, i) => (
          <div
            key={i}
            style={{
              width: 120,
              height: 120,
              borderRadius: "50%",
              backgroundColor: i < filledCount ? accent : primary,
              opacity: i < filledCount ? 1 : 0.2,
            }}
          />
        ))}
      </div>

      <div
        style={{
          color: primary,
          fontSize: 54,
          marginTop: 60,
          textAlign: "center",
          maxWidth: 900,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
