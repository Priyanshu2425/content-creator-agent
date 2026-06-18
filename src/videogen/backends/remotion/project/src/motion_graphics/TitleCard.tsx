import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { MgTitleCardProps } from "./types";

export const MgTitleCard: React.FC<MgTitleCardProps> = ({
  headline,
  subtext,
  animation_style,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const progress =
    animation_style === "spring"
      ? spring({ frame, fps, config: { damping: 14, stiffness: 120 }, durationInFrames: Math.floor(fps * 0.6) })
      : interpolate(frame, [0, Math.floor(fps * 0.5)], [0, 1], { extrapolateRight: "clamp" });

  const translateY =
    animation_style === "slide_up"
      ? interpolate(frame, [0, Math.floor(fps * 0.4)], [80, 0], { extrapolateRight: "clamp" })
      : animation_style === "spring"
      ? interpolate(progress, [0, 1], [60, 0])
      : 0;

  const opacity = interpolate(frame, [0, Math.floor(fps * 0.25)], [0, 1], {
    extrapolateRight: "clamp",
  });

  const subtextOpacity = interpolate(
    frame,
    [Math.floor(fps * 0.3), Math.floor(fps * 0.7)],
    [0, 1],
    { extrapolateRight: "clamp" }
  );

  // Fade out last 0.4s
  const fadeOut = interpolate(
    frame,
    [durationInFrames - Math.floor(fps * 0.4), durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        background,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: "0 80px",
        opacity: fadeOut,
        fontFamily,
      }}
    >
      {/* Accent bar */}
      <div
        style={{
          width: interpolate(frame, [0, Math.floor(fps * 0.4)], [0, 160], { extrapolateRight: "clamp" }),
          height: 8,
          background: accent,
          borderRadius: 4,
          marginBottom: 40,
        }}
      />
      {/* Headline */}
      <div
        style={{
          color: primary,
          fontSize: 88,
          fontWeight: 900,
          lineHeight: 1.1,
          textAlign: "center",
          opacity,
          transform: `translateY(${translateY}px)`,
          letterSpacing: "-1px",
        }}
      >
        {headline}
      </div>
      {/* Subtext */}
      {subtext ? (
        <div
          style={{
            color: accent,
            fontSize: 44,
            fontWeight: 500,
            textAlign: "center",
            marginTop: 36,
            opacity: subtextOpacity,
            maxWidth: 860,
            lineHeight: 1.4,
          }}
        >
          {subtext}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
