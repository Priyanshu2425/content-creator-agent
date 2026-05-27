// The IR interpreter. Dispatches on each layer's `kind` -- never on overlay type or caption style --
// so this stays the single place Remotion code lives (ADR 0002). It understands `media` (full-frame
// host video), `audio` (the voiceover, muxed onto the output), and `text` (captions: paints the
// compiled visual props and animates the opacity/scale tracks through the shared keyframe sampler).

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
import type { AudioLayer, Layer, MainProps, MediaLayer, TextLayer } from "./types";

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

// Captions sit in the lower third, centered, painted from the layer's compiled props. The pop-in of
// a kinetic caption rides the same opacity/transform tracks the media layer uses, so the keyframe
// sampler -- not per-style code -- drives the animation.
const TextLayerView: React.FC<{ layer: TextLayer; from: number }> = ({ layer, from }) => {
  const { fps } = useVideoConfig();
  const frame = from + useCurrentFrame(); // absolute timeline frame for the sampler
  const opacity = sample(layer.opacity, frame, fps, 1);
  const scale = sample(layer.transform?.scale, frame, fps, 1);
  const p = layer.props;
  const text = layer.runs.map((run) => run.text).join(" ");
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: "20%",
      }}
    >
      <div
        style={{
          opacity,
          transform: `scale(${scale})`,
          maxWidth: "82%",
          textAlign: "center",
          fontFamily: "Arial, Helvetica, sans-serif",
          fontSize: p.font_size,
          fontWeight: p.font_weight,
          lineHeight: 1.15,
          color: p.color,
          background: p.background ?? "transparent",
          borderRadius: p.border_radius,
          padding: `${p.padding_y}px ${p.padding_x}px`,
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

const LayerView: React.FC<{ layer: Layer; from: number }> = ({ layer, from }) => {
  switch (layer.kind) {
    case "media":
      return <MediaLayerView layer={layer} from={from} />;
    case "audio":
      return <AudioLayerView layer={layer} />;
    case "text":
      return <TextLayerView layer={layer} from={from} />;
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
