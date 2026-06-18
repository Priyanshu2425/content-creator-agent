import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { MgLowerThirdProps } from "./types";

export const MgLowerThird: React.FC<MgLowerThirdProps> = ({
  name,
  role,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Slide in from left
  const slideIn = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 140 },
    durationInFrames: Math.floor(fps * 0.5),
  });
  const translateX = interpolate(slideIn, [0, 1], [-600, 0]);

  // Fade out last 0.5s
  const fadeOut = interpolate(
    frame,
    [durationInFrames - Math.floor(fps * 0.5), durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const textOpacity = interpolate(frame, [Math.floor(fps * 0.15), Math.floor(fps * 0.4)], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{ fontFamily, pointerEvents: "none" }}
    >
      {/* Positioned at lower-third */}
      <div
        style={{
          position: "absolute",
          bottom: 320,
          left: 0,
          right: 0,
          padding: "0 60px",
          opacity: fadeOut,
          transform: `translateX(${translateX}px)`,
        }}
      >
        {/* Bar background */}
        <div
          style={{
            background: background,
            borderLeft: `8px solid ${accent}`,
            padding: "24px 36px",
            display: "inline-block",
            minWidth: 480,
            maxWidth: 900,
          }}
        >
          <div
            style={{
              color: primary,
              fontSize: 52,
              fontWeight: 800,
              lineHeight: 1.1,
              opacity: textOpacity,
            }}
          >
            {name}
          </div>
          {role ? (
            <div
              style={{
                color: accent,
                fontSize: 34,
                fontWeight: 500,
                marginTop: 8,
                opacity: textOpacity,
              }}
            >
              {role}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
