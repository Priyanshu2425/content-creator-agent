// The IR interpreter. Dispatches on each layer's `kind` for media and audio -- never on overlay type
// or layout name. A `text` layer is the one place the backend branches on a style name: it is
// dispatched through the caption renderer registry (ADR 0010 amends ADR 0002 for captions only) by
// its `style` id, with a safe fallback for an unknown id. It understands `media` (a video clip or an
// image still, placed full-frame or in a normalized sub-rect), `audio` (the voiceover, muxed onto
// the output), and `text` (captions + the title hook, painted by their registered renderer).

import React from "react";
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Img,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { getImageDimensions, getVideoMetadata } from "@remotion/media-utils";
import { resolveCaptionRenderer } from "./captions/registry";
import { sample } from "./sampler";
import type { AudioLayer, HookLayer, Layer, MainProps, MediaLayer, Rect } from "./types";
import { HookOverlay } from "./brand_card/CenterHookCard";

// A normalized rect becomes a positioned box; its absence fills the frame. Geometry is generic --
// the backend never knows which layout produced it.
function boxStyle(rect: Rect | null | undefined): React.CSSProperties {
  if (!rect) {
    return { position: "absolute", inset: 0 };
  }
  return {
    position: "absolute",
    left: `${rect.x * 100}%`,
    top: `${rect.y * 100}%`,
    width: `${rect.width * 100}%`,
    height: `${rect.height * 100}%`,
  };
}

// How the source media sits inside its box. Without a crop it covers the box (centered cover). With
// a crop, only that normalized source sub-rect is shown: the media is enlarged so the crop window
// maps onto the box (width 1/cw, height 1/ch) and offset so the window's top-left sits at the box
// origin; objectFit stays `cover` so the window fills the box with no letterboxing.
function fillStyle(crop: Rect | null | undefined): React.CSSProperties {
  if (!crop) {
    return { width: "100%", height: "100%", objectFit: "cover" };
  }
  return {
    position: "absolute",
    width: `${100 / crop.width}%`,
    height: `${100 / crop.height}%`,
    left: `${(-crop.x * 100) / crop.width}%`,
    top: `${(-crop.y * 100) / crop.height}%`,
    objectFit: "cover",
  };
}

// Read the source's intrinsic aspect (cached by media-utils) so a wider-than-frame asset (e.g. a
// 16:9 clip in a 9:16 reel) can be centered/fit rather than cropped. Returns null until resolved.
function useSourceAspect(src: string, content: "video" | "image"): number | null {
  const [aspect, setAspect] = React.useState<number | null>(null);
  React.useEffect(() => {
    const handle = delayRender(`aspect ${src}`);
    const p =
      content === "image" ? getImageDimensions(src) : getVideoMetadata(src);
    p.then((d: { width: number; height: number }) => {
      setAspect(d.height ? d.width / d.height : null);
      continueRender(handle);
    }).catch(() => continueRender(handle));
    return () => continueRender(handle);
  }, [src, content]);
  return aspect;
}

const MediaLayerView: React.FC<{ layer: MediaLayer; from: number }> = ({ layer, from }) => {
  const { fps, width, height } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const opacity = sample(layer.opacity, frame, fps, 1);
  const scale = sample(layer.transform?.scale, frame, fps, 1);
  const tx = sample(layer.transform?.translate_x, frame, fps, 0);
  const ty = sample(layer.transform?.translate_y, frame, fps, 0);
  const src = staticFile(layer.src);
  // A wider-than-frame source (e.g. 16:9 in a 9:16 reel) is centered and fully shown ("contain",
  // letterboxed against the black base) instead of cropped to cover. An explicit crop wins (the
  // author chose a window), and a portrait/matching source still covers. The aspect arrives async;
  // until it does, default to cover so a frame is never blank.
  const aspect = useSourceAspect(src, layer.content);
  const frameAspect = width / height;
  const fit: "cover" | "contain" =
    !layer.crop && aspect !== null && aspect > frameAspect + 0.01 ? "contain" : "cover";
  const fill = layer.crop
    ? fillStyle(layer.crop)
    : { width: "100%", height: "100%", objectFit: fit };
  // startFrom seeks the source to the layer's in-point so a new Sequence doesn't replay from 0.
  // muted suppresses the video's embedded audio; the AudioLayer is the sole audio master.
  const startFrom = Math.round((layer.in ?? 0) * fps);
  return (
    <div
      style={{
        ...boxStyle(layer.rect),
        opacity,
        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
        overflow: "hidden",
      }}
    >
      {layer.content === "image" ? (
        <Img src={src} style={fill} />
      ) : (
        <OffthreadVideo src={src} startFrom={startFrom} muted style={fill} />
      )}
    </div>
  );
};

const AudioLayerView: React.FC<{ layer: AudioLayer }> = ({ layer }) => {
  const { fps } = useVideoConfig();
  const startFrom = Math.round((layer.in ?? 0) * fps);
  return <Audio src={staticFile(layer.src)} startFrom={startFrom} />;
};

// The opening text-hook (ADR 0013): rendered by the CenterHookCard's transparent HookOverlay over
// the live timeline. The renderer owns the cursor/click animation; the layer carries only semantics.
const HookLayerView: React.FC<{ layer: HookLayer }> = ({ layer }) => {
  const { fps } = useVideoConfig();
  return (
    <HookOverlay
      fps={fps}
      hookText={layer.text}
      textColor={layer.text_color}
      boxColor={layer.box_color}
      brand={layer.brand}
      vAlign={layer.placement}
    />
  );
};

const LayerView: React.FC<{ layer: Layer; from: number }> = ({ layer, from }) => {
  switch (layer.kind) {
    case "media":
      return <MediaLayerView layer={layer} from={from} />;
    case "audio":
      return <AudioLayerView layer={layer} />;
    case "text": {
      // The one name-keyed dispatch: resolve the caption renderer by the layer's style id (ADR
      // 0010), falling back safely on an unknown id rather than crashing.
      const CaptionView = resolveCaptionRenderer(layer.style);
      return <CaptionView layer={layer} from={from} />;
    }
    case "hook":
      return <HookLayerView layer={layer} />;
    default:
      return null;
  }
};

export const Main: React.FC<MainProps> = ({ ir }) => {
  const { fps } = useVideoConfig();
  // Paint in z order; layers carry absolute-second spans turned into Sequence frame windows.
  const layers = [...ir.layers].sort((a, b) => a.z - b.z);
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {layers.map((layer, i) => {
        const from = Math.round(layer.start * fps);
        const durationInFrames = Math.max(1, Math.round((layer.end - layer.start) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={durationInFrames}>
            <LayerView layer={layer} from={from} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
