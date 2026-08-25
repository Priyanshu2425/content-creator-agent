// Smoke-test composition: a centered "hook" overlaid on a real video for the first few seconds.
// The hook text sits dead-center with a configurable highlight-box background (no full-frame bg of
// its own -- the video shows through), carries a "buildspace labs" wordmark, and reuses the cursor
// fly-in + click animation. Configurable via props (hook text, text/box colors, brand, video).
//
// Render: copy the source video to public/, then
//   npx remotion render src/index.ts CenterHookCard out.mp4 \
//     --props='{"videoSrc":"smoke_host.mp4","hookText":"...","textColor":"#0A0A0A","boxColor":"#FF6A00"}'

import React from "react";
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";

const { fontFamily } = loadFont();

export type CenterHookCardProps = {
  fps: number;
  duration_s: number;
  videoSrc: string; // a file in public/, referenced via staticFile
  hookText: string;
  textColor: string; // the hook text colour (configurable)
  boxColor: string; // the highlight-box background behind the text (configurable)
  brand: string; // small wordmark, e.g. "buildspace labs"
  vAlign?: "center" | "top"; // where the hook sits (default center)
};

const BLACK = "#0A0A0A";
const WHITE = "#FFFFFF";

// Chunky pixel-art cursor (black fill, white pixel outline) -- same look as the poster smoke test.
const PixelCursor: React.FC<{ size: number }> = ({ size }) => {
  const grid = [
    "2000000000", "2200000000", "2120000000", "2112000000",
    "2111200000", "2111120000", "2111112000", "2111111200",
    "2111111120", "2111122220", "2112112000", "2120212000",
    "2200211200", "2000211200", "0000021200", "0000022000",
  ];
  const px = size / 10;
  return (
    <svg width={size} height={px * grid.length} shapeRendering="crispEdges">
      {grid.flatMap((row, y) =>
        row.split("").map((c, x) =>
          c === "0" ? null : (
            <rect key={`${x}-${y}`} x={x * px} y={y * px} width={px} height={px}
              fill={c === "1" ? BLACK : WHITE} />
          ),
        ),
      )}
    </svg>
  );
};

// Props for the transparent hook overlay -- the kernel hook layer (ADR 0013) renders this directly
// over the live timeline; the standalone CenterHookCard wraps it over its own video.
export type HookOverlayProps = {
  fps: number;
  hookText: string;
  textColor: string;
  boxColor: string;
  brand: string;
  vAlign?: "center" | "top";
};

// The hook visual + cursor-click animation, with NO background of its own (transparent). This is the
// reusable piece: it paints over whatever is beneath -- the live IR timeline (kernel layer) or the
// standalone card's video.
export const HookOverlay: React.FC<HookOverlayProps> = ({
  fps,
  hookText,
  textColor,
  boxColor,
  brand,
  vAlign = "center",
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const hookY = vAlign === "top" ? height * 0.2 : height * 0.5;

  // Hook rises + scales in (0 -> ~0.5s).
  const intro = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });
  const hookScale = interpolate(intro, [0, 1], [0.86, 1]);
  const hookOpacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  // Cursor flies from the bottom-right to the hook, arriving ~frame 40.
  const travel = interpolate(frame, [12, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  const cx = interpolate(travel, [0, 1], [width * 1.05, width * 0.5]);
  const cy = interpolate(travel, [0, 1], [height * 1.05, hookY]);

  // Click at ~frame 44: cursor scale dip + ripple + hook pulse.
  const clickDip = frame >= 44 && frame < 52 ? 1 - 0.2 * Math.sin(((frame - 44) / 8) * Math.PI) : 1;
  const ripple = interpolate(frame, [44, 66], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const rippleSize = interpolate(ripple, [0, 1], [0, width * 0.5]);
  const rippleOpacity = interpolate(ripple, [0, 1], [0.6, 0]);
  const pulse = frame >= 44 && frame < 56 ? 1 + 0.04 * Math.sin(((frame - 44) / 12) * Math.PI) : 1;

  return (
    <AbsoluteFill style={{ fontFamily }}>
      {/* buildspace labs wordmark, top-center */}
      <div
        style={{
          position: "absolute",
          top: height * 0.06,
          width: "100%",
          textAlign: "center",
          color: WHITE,
          fontSize: width * 0.034,
          fontWeight: 700,
          letterSpacing: "0.04em",
          opacity: hookOpacity,
          textShadow: "0 2px 8px rgba(0,0,0,0.5)",
        }}
      >
        <span style={{ color: boxColor }}>buildspace</span> {brand.replace(/^buildspace\s*/i, "")}
      </div>

      {/* hook with a configurable highlight box behind the text; centered or top-aligned */}
      <AbsoluteFill
        style={{
          justifyContent: vAlign === "top" ? "flex-start" : "center",
          alignItems: "center",
          paddingTop: vAlign === "top" ? height * 0.14 : 0,
        }}
      >
        <div
          style={{
            maxWidth: "82%",
            textAlign: "center",
            transform: `scale(${hookScale * pulse})`,
            opacity: hookOpacity,
          }}
        >
          <span
            style={{
              background: boxColor,
              color: textColor,
              fontSize: width * 0.085,
              fontWeight: 800,
              lineHeight: 1.45,
              letterSpacing: "-0.01em",
              padding: `${width * 0.012}px ${width * 0.022}px`,
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
          >
            {hookText}
          </span>
        </div>
      </AbsoluteFill>

      {/* click ripple */}
      <div
        style={{
          position: "absolute",
          left: cx,
          top: cy,
          width: rippleSize,
          height: rippleSize,
          marginLeft: -rippleSize / 2,
          marginTop: -rippleSize / 2,
          borderRadius: "50%",
          border: `${width * 0.006}px solid ${WHITE}`,
          opacity: rippleOpacity,
        }}
      />

      {/* cursor */}
      <div
        style={{
          position: "absolute",
          left: cx,
          top: cy,
          transform: `scale(${clickDip})`,
          filter: "drop-shadow(0 6px 10px rgba(0,0,0,0.4))",
        }}
      >
        <PixelCursor size={width * 0.13} />
      </div>
    </AbsoluteFill>
  );
};

// Standalone smoke composition: the hook overlay over its own video background. The kernel hook
// layer (Main.tsx) uses HookOverlay directly over the live timeline and does not need this wrapper.
export const CenterHookCard: React.FC<CenterHookCardProps> = ({
  fps,
  videoSrc,
  hookText,
  textColor,
  boxColor,
  brand,
  vAlign = "center",
}) => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile(videoSrc)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    <HookOverlay
      fps={fps}
      hookText={hookText}
      textColor={textColor}
      boxColor={boxColor}
      brand={brand}
      vAlign={vAlign}
    />
  </AbsoluteFill>
);
