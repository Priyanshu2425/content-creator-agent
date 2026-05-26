// The IR interpreter. Dispatches on each layer's `kind` -- never on overlay type -- so this stays
// the single place Remotion code lives (ADR 0002). Phase 2 understands `media` (full-frame host
// video) and `audio` (the voiceover, muxed onto the output); `text` is Phase 3.

import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { sample } from "./sampler";
import type { AudioLayer, Layer, MainProps, MediaLayer } from "./types";

const MediaLayerView: React.FC<{ layer: MediaLayer; from: number }> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const opacity = sample(layer.opacity, frame, fps, 1);
  const scale = sample(layer.transform?.scale, frame, fps, 1);
  const tx = sample(layer.transform?.translate_x, frame, fps, 0);
  const ty = sample(layer.transform?.translate_y, frame, fps, 0);
  return (
    <AbsoluteFill style={{ opacity, transform: `translate(${tx}px, ${ty}px) scale(${scale})` }}>
      <OffthreadVideo
        src={staticFile(layer.src)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};

const AudioLayerView: React.FC<{ layer: AudioLayer }> = ({ layer }) => {
  return <Audio src={staticFile(layer.src)} />;
};

const LayerView: React.FC<{ layer: Layer; from: number }> = ({ layer, from }) => {
  switch (layer.kind) {
    case "media":
      return <MediaLayerView layer={layer} from={from} />;
    case "audio":
      return <AudioLayerView layer={layer} />;
    case "text":
      return null; // Phase 3: caption text layers
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
