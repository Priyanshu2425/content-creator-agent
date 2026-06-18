// Smoke-test composition: an animated recreation of the Chazon "Who We Are" brand poster.
// Uses Hanken Grotesk (the closest free match to the poster's grotesque) loaded via
// @remotion/google-fonts, self-contained so it renders standalone via `remotion render`.

import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/HankenGrotesk";

const { fontFamily } = loadFont();

export type ChazonCardProps = {
  fps: number;
  duration_s: number;
};

const DARK = "#1e1f1c";
const LIME = "#c6f03e";
const OLIVE = "#5d7d1c";
const PAPER = "#ecebe4";

const Target: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="2.2" />
    <circle cx="12" cy="12" r="3.6" stroke={color} strokeWidth="2.2" />
    <circle cx="12" cy="12" r="1.1" fill={color} />
    <path d="M12 1.5v3.5M12 19v3.5M1.5 12H5M19 12h3.5" stroke={color} strokeWidth="2.2" />
  </svg>
);

export const ChazonCard: React.FC<ChazonCardProps> = ({ fps }) => {
  const frame = useCurrentFrame();

  const rise = (start: number, dist = 30) => ({
    opacity: interpolate(frame, [start, start + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    transform: `translateY(${interpolate(frame, [start, start + 12], [dist, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
  });

  const pop = (start: number, rot: number) => {
    const s = spring({ frame: frame - start, fps, config: { damping: 11, stiffness: 130 } });
    return {
      opacity: interpolate(frame, [start, start + 5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
      transform: `scale(${s}) rotate(${rot}deg)`,
    };
  };

  const wipe = interpolate(frame, [46, 62], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tri = (start: number) => interpolate(frame, [start, start + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: PAPER, fontFamily, color: DARK }}>
      {/* engineering grid */}
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(#00000010 1px, transparent 1px), linear-gradient(90deg, #00000010 1px, transparent 1px)`,
          backgroundSize: `44px 44px`,
        }}
      />
      {/* lime corner gradients with a slow breathe */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(520px 440px at 100% -3%, ${LIME}, transparent 58%), radial-gradient(440px 380px at -3% 103%, ${LIME}, transparent 58%)`,
          transform: `scale(${interpolate(Math.sin(frame / 26), [-1, 1], [0.97, 1.05])})`,
        }}
      />

      <div style={{ position: "absolute", inset: 0, padding: "60px 64px", display: "flex", flexDirection: "column" }}>
        {/* header */}
        <div style={{ ...rise(0, 16), display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", fontSize: 34, fontWeight: 800, letterSpacing: -0.5 }}>
            Chaz<span style={{ display: "inline-flex", margin: "0 1px" }}><Target size={28} color={OLIVE} /></span>n
          </div>
          <div style={{ fontSize: 23, fontWeight: 600 }}>
            <span style={{ background: LIME, padding: "2px 9px", borderRadius: 5 }}>Plain</span> vision.{" "}
            <span style={{ fontWeight: 900 }}>Bold</span> brands
          </div>
        </div>

        {/* heading */}
        <div style={{ ...rise(12, 26), textAlign: "center", marginTop: 64, fontSize: 64, fontWeight: 800, letterSpacing: -1 }}>
          Who We Are:
        </div>

        {/* body */}
        <div style={{ marginTop: 48, fontSize: 110, lineHeight: 1.08, fontWeight: 800, letterSpacing: -2.5 }}>
          <div style={{ ...rise(22), display: "flex", alignItems: "center", gap: 22 }}>
            <span style={{ transform: `scale(${tri(20)})`, color: LIME, fontSize: 70, lineHeight: 1 }}>▶</span>
            We build
          </div>
          <div style={{ ...rise(34), display: "flex", alignItems: "center", gap: 26 }}>
            <span style={{ position: "relative", color: OLIVE, fontWeight: 900 }}>
              <span style={{ position: "absolute", inset: "10px -14px", background: LIME, transformOrigin: "left center", transform: `scaleX(${wipe})`, zIndex: -1 }} />
              brands
            </span>
            <span>that feel</span>
          </div>
          <div style={{ ...rise(46), display: "flex", alignItems: "baseline", gap: 18 }}>
            intentional.
            <span style={{ transform: `scale(${tri(52)})`, color: LIME, fontSize: 58, lineHeight: 1 }}>▼</span>
          </div>
          <div style={rise(58)}>
            From <span style={{ fontStyle: "italic", fontWeight: 900 }}>identity</span>
          </div>
          <div style={rise(70)}>
            to <span style={{ fontStyle: "italic", fontWeight: 900 }}>execution.</span>
          </div>
        </div>

        {/* tag pills */}
        <Pill style={pop(64, -3)} top={360} left={540} label="Strategy first" />
        <Pill style={pop(80, -5)} top={690} left={470} label="Design with meaning" />
        <Pill style={pop(96, -2)} top={1010} left={150} label="Built to scale" />

        {/* contact bar */}
        <div style={{ ...rise(98, 34), position: "absolute", left: 64, right: 64, bottom: 56, display: "flex", gap: 16, justifyContent: "center" }}>
          <div style={barPill}>
            <span style={{ letterSpacing: 5, fontSize: 22 }}>✕ f ⦿ ♪</span>
            <span style={{ fontWeight: 700 }}>@chazoncreagency</span>
          </div>
          <div style={barPill}>
            <Target size={22} color={LIME} />
            <span style={{ fontWeight: 700 }}>+23468445662</span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const barPill: React.CSSProperties = {
  background: DARK,
  color: "#f4f4f0",
  borderRadius: 999,
  padding: "16px 28px",
  display: "flex",
  alignItems: "center",
  gap: 12,
  fontSize: 23,
};

const Pill: React.FC<{ style: React.CSSProperties; top: number; left: number; label: string }> = ({ style, top, left, label }) => (
  <div
    style={{
      ...style,
      position: "absolute",
      top,
      left,
      background: LIME,
      color: DARK,
      borderRadius: 999,
      padding: "11px 22px 11px 16px",
      display: "flex",
      alignItems: "center",
      gap: 11,
      fontSize: 34,
      fontWeight: 700,
      boxShadow: "0 8px 22px #00000026",
      whiteSpace: "nowrap",
    }}
  >
    <Target size={28} color={OLIVE} />
    {label}
  </div>
);
