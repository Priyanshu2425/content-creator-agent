import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { MgCtaCardProps } from "./types";

export const MgCtaCard: React.FC<MgCtaCardProps> = ({
  headline,
  subtext,
  cta,
  background,
  primary,
  accent,
  accent2,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const headlineSpring = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 100 },
    durationInFrames: Math.floor(fps * 0.7),
  });
  const headlineY = interpolate(headlineSpring, [0, 1], [100, 0]);

  const subtextOpacity = interpolate(
    frame,
    [Math.floor(fps * 0.4), Math.floor(fps * 0.8)],
    [0, 1],
    { extrapolateRight: "clamp" }
  );

  const ctaSpring = spring({
    frame: frame - Math.floor(fps * 0.6),
    fps,
    config: { damping: 12, stiffness: 90 },
    durationInFrames: Math.floor(fps * 0.6),
  });
  const ctaScale = interpolate(ctaSpring, [0, 1], [0.6, 1]);
  const ctaOpacity = interpolate(ctaSpring, [0, 0.3], [0, 1], { extrapolateRight: "clamp" });

  // Overall fade out
  const fadeOut = interpolate(
    frame,
    [durationInFrames - Math.floor(fps * 0.5), durationInFrames],
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
      {/* Headline */}
      <div
        style={{
          color: primary,
          fontSize: 96,
          fontWeight: 900,
          lineHeight: 1.05,
          textAlign: "center",
          transform: `translateY(${headlineY}px)`,
          opacity: headlineSpring,
          letterSpacing: "-2px",
        }}
      >
        {headline}
      </div>

      {/* Subtext */}
      {subtext ? (
        <div
          style={{
            color: primary,
            fontSize: 44,
            fontWeight: 400,
            textAlign: "center",
            marginTop: 40,
            opacity: subtextOpacity * 0.7,
            maxWidth: 860,
            lineHeight: 1.5,
          }}
        >
          {subtext}
        </div>
      ) : null}

      {/* CTA pill button */}
      {cta ? (
        <div
          style={{
            marginTop: 80,
            background: accent,
            color: accent2 || "#000000",
            fontSize: 48,
            fontWeight: 800,
            padding: "28px 72px",
            borderRadius: 100,
            transform: `scale(${ctaScale})`,
            opacity: ctaOpacity,
            letterSpacing: "0.5px",
          }}
        >
          {cta}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
