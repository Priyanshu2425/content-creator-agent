import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { MgKineticTextProps } from "./types";

const GLITCH_CHARS = "!@#$%^&*<>?|{}~";

function glitchChar(char: string, frame: number, index: number): string {
  if (char === " ") return " ";
  const seed = (frame * 7 + index * 13) % GLITCH_CHARS.length;
  return GLITCH_CHARS[seed];
}

const WordSpring: React.FC<{
  word: string;
  index: number;
  totalWords: number;
  primary: string;
  accent: string;
  fontSize: number;
  fps: number;
}> = ({ word, index, totalWords, primary, accent, fontSize, fps }) => {
  const frame = useCurrentFrame();
  const delay = Math.floor((index / totalWords) * fps * 0.8);
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 14, stiffness: 130 },
    durationInFrames: Math.floor(fps * 0.4),
  });
  const y = interpolate(progress, [0, 1], [40, 0]);
  const opacity = interpolate(progress, [0, 0.4], [0, 1], { extrapolateRight: "clamp" });
  // Alternate accent color for emphasis words (every 3rd word)
  const color = index % 4 === 2 ? accent : primary;

  return (
    <span
      style={{
        display: "inline-block",
        opacity,
        transform: `translateY(${y}px)`,
        marginRight: "0.22em",
        color,
        fontSize,
        fontWeight: 900,
        lineHeight: 1.15,
      }}
    >
      {word}
    </span>
  );
};

const TypewriterText: React.FC<{
  text: string;
  primary: string;
  fontSize: number;
  fps: number;
}> = ({ text, primary, fontSize, fps }) => {
  const frame = useCurrentFrame();
  const charsPerFrame = text.length / (fps * 1.2);
  const visibleChars = Math.min(text.length, Math.floor(frame * charsPerFrame));
  const cursor = frame % Math.floor(fps / 2) < Math.floor(fps / 4) ? "|" : "";

  return (
    <div
      style={{
        color: primary,
        fontSize,
        fontWeight: 800,
        lineHeight: 1.3,
        textAlign: "center",
        letterSpacing: "1px",
        fontFamily: "monospace",
      }}
    >
      {text.slice(0, visibleChars)}
      <span style={{ opacity: 0.7 }}>{cursor}</span>
    </div>
  );
};

const GlitchText: React.FC<{
  text: string;
  primary: string;
  accent: string;
  fontSize: number;
  fps: number;
}> = ({ text, primary, accent, fontSize, fps }) => {
  const frame = useCurrentFrame();
  // Reveal: each char appears after a threshold
  const revealFrames = fps * 0.9;
  const revealedCount = Math.floor((frame / revealFrames) * text.length);

  return (
    <div
      style={{
        color: primary,
        fontSize,
        fontWeight: 900,
        letterSpacing: "2px",
        textAlign: "center",
        lineHeight: 1.2,
      }}
    >
      {text.split("").map((char, i) => {
        if (i < revealedCount) {
          return (
            <span key={i} style={{ color: i % 5 === 0 ? accent : primary }}>
              {char}
            </span>
          );
        }
        if (i < revealedCount + 3) {
          return (
            <span key={i} style={{ color: accent, opacity: 0.8 }}>
              {glitchChar(char, frame, i)}
            </span>
          );
        }
        return (
          <span key={i} style={{ opacity: 0.15 }}>
            {char}
          </span>
        );
      })}
    </div>
  );
};

export const MgKineticText: React.FC<MgKineticTextProps> = ({
  text,
  animation_style,
  font_size,
  background,
  primary,
  accent,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const words = text.split(" ").filter(Boolean);

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
        justifyContent: "center",
        alignItems: "center",
        padding: "0 80px",
        opacity: fadeOut,
        fontFamily,
      }}
    >
      {animation_style === "typewriter" ? (
        <TypewriterText text={text} primary={primary} fontSize={font_size} fps={fps} />
      ) : animation_style === "glitch" ? (
        <GlitchText text={text} primary={primary} accent={accent} fontSize={font_size} fps={fps} />
      ) : (
        // word_spring (default)
        <div style={{ textAlign: "center", display: "flex", flexWrap: "wrap", justifyContent: "center" }}>
          {words.map((word, i) => (
            <WordSpring
              key={i}
              word={word}
              index={i}
              totalWords={words.length}
              primary={primary}
              accent={accent}
              fontSize={font_size}
              fps={fps}
            />
          ))}
        </div>
      )}
    </AbsoluteFill>
  );
};
