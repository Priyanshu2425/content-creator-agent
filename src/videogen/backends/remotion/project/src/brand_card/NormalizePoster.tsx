// Smoke-test composition: a square (1:1) animated recreation of the "Things We Should Normalize"
// poster. The text rises in, then a chunky pixel cursor flies in from the corner and clicks the
// title (a scale dip + a ripple ring + a title pulse). Self-contained; renders standalone via
// `remotion render src/index.ts NormalizePoster out.mp4`.

import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";

const { fontFamily } = loadFont();

export type NormalizePosterProps = {
  fps: number;
  duration_s: number;
};

const BLUE = "#1A1AFF";
const WHITE = "#FFFFFF";
const BLACK = "#0A0A0A";

// A chunky pixel-art cursor (black fill, white pixel outline) drawn as an SVG of crisp squares so it
// keeps the blocky look of the poster's cursor at any scale.
const PixelCursor: React.FC<{ size: number }> = ({ size }) => {
  // 1 = black pixel, 2 = white outline pixel, 0 = transparent. Classic up-left pointer.
  const grid = [
    "2000000000",
    "2200000000",
    "2120000000",
    "2112000000",
    "2111200000",
    "2111120000",
    "2111112000",
    "2111111200",
    "2111111120",
    "2111122220",
    "2112112000",
    "2120212000",
    "2200211200",
    "2000211200",
    "0000021200",
    "0000022000",
  ];
  const px = size / 10;
  return (
    <svg width={size} height={px * grid.length} shapeRendering="crispEdges">
      {grid.flatMap((row, y) =>
        row.split("").map((c, x) =>
          c === "0" ? null : (
            <rect
              key={`${x}-${y}`}
              x={x * px}
              y={y * px}
              width={px}
              height={px}
              fill={c === "1" ? BLACK : WHITE}
            />
          ),
        ),
      )}
    </svg>
  );
};

export const NormalizePoster: React.FC<NormalizePosterProps> = ({ fps }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();

  const rise = (start: number, dist = 26) => ({
    opacity: interpolate(frame, [start, start + 12], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    transform: `translateY(${interpolate(frame, [start, start + 12], [dist, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })}px)`,
  });

  // Cursor: fly from the bottom-right corner to the title, arriving ~frame 54.
  const travel = interpolate(frame, [22, 54], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  const cursorX = interpolate(travel, [0, 1], [width * 1.05, width * 0.5]);
  const cursorY = interpolate(travel, [0, 1], [width * 1.05, width * 0.62]);

  // Click at ~frame 58: a quick scale dip on the cursor.
  const click = spring({ frame: frame - 58, fps, config: { damping: 9, stiffness: 220 } });
  const clickDip = frame >= 58 && frame < 66 ? 1 - 0.18 * Math.sin((frame - 58) / 8 * Math.PI) : 1;

  // Ripple ring expands + fades right after the click.
  const ripple = interpolate(frame, [58, 78], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rippleSize = interpolate(ripple, [0, 1], [0, width * 0.34]);
  const rippleOpacity = interpolate(ripple, [0, 1], [0.7, 0]);

  // Title pulse on click.
  const pulse = frame >= 58 ? 1 + 0.03 * Math.max(0, click - click * click) * 4 : 1;

  const small: React.CSSProperties = {
    position: "absolute",
    fontSize: width * 0.026,
    fontWeight: 700,
    letterSpacing: "0.02em",
    color: WHITE,
  };

  return (
    <AbsoluteFill style={{ backgroundColor: BLUE, fontFamily, color: WHITE }}>
      {/* faint dot grid */}
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${WHITE}22 1.2px, transparent 1.2px)`,
          backgroundSize: `${width * 0.05}px ${width * 0.05}px`,
          opacity: 0.5,
        }}
      />

      {/* top row */}
      <div style={{ ...small, top: width * 0.07, left: width * 0.08, ...rise(2) }}>things we should</div>
      <div style={{ ...small, top: width * 0.07, right: width * 0.08, ...rise(4) }}>normalize</div>

      {/* big title */}
      <div
        style={{
          position: "absolute",
          top: width * 0.2,
          left: width * 0.08,
          lineHeight: 0.92,
          fontSize: width * 0.155,
          fontWeight: 800,
          letterSpacing: "-0.02em",
          transform: `scale(${pulse})`,
          transformOrigin: "left center",
        }}
      >
        {["Things", "We", "Should", "Normalize"].map((w, i) => (
          <div key={w} style={rise(6 + i * 4)}>
            {w}
          </div>
        ))}
      </div>

      {/* subtitle */}
      <div
        style={{
          position: "absolute",
          top: width * 0.68,
          left: width * 0.08,
          fontSize: width * 0.058,
          fontWeight: 400,
          lineHeight: 1.1,
          ...rise(24),
        }}
      >
        Designer&rsquo;s side
        <br />
        at Marketing Agency
      </div>

      {/* bottom row */}
      <div style={{ ...small, bottom: width * 0.06, left: width * 0.08, ...rise(28) }}>
        sharing as a designer
      </div>
      <div style={{ ...small, bottom: width * 0.06, right: width * 0.08, ...rise(30) }}>
        at marketing agency
      </div>

      {/* click ripple */}
      <div
        style={{
          position: "absolute",
          left: cursorX,
          top: cursorY,
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
          left: cursorX,
          top: cursorY,
          transform: `scale(${clickDip})`,
          filter: "drop-shadow(0 6px 10px rgba(0,0,0,0.35))",
        }}
      >
        <PixelCursor size={width * 0.16} />
      </div>
    </AbsoluteFill>
  );
};
