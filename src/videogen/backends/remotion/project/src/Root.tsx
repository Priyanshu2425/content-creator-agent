// Registers the single "Main" composition. Per-render metadata (width, height, fps,
// durationInFrames) is derived from the IR in the incoming props via calculateMetadata, so the
// voiceover's duration (the master clock, ADR 0005) and the host's frame rate flow straight from
// the IR. The static defaults below only seed Remotion Studio when no props are supplied.

import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { Main } from "./Main";
import type { IR, MainProps } from "./types";

const FALLBACK_IR: IR = {
  width: 1080,
  height: 1920,
  fps: 30,
  duration: 1,
  layers: [],
};

// seconds -> frames is fixed here: durationInFrames = round(duration * fps). The Python backend
// uses the same rule for the still frame index, so timing does not drift across the boundary.
const calculateMetadata: CalculateMetadataFunction<MainProps> = ({ props }) => {
  const { ir } = props;
  return {
    width: ir.width,
    height: ir.height,
    fps: ir.fps,
    durationInFrames: Math.max(1, Math.round(ir.duration * ir.fps)),
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Main"
      component={Main}
      width={FALLBACK_IR.width}
      height={FALLBACK_IR.height}
      fps={FALLBACK_IR.fps}
      durationInFrames={Math.round(FALLBACK_IR.duration * FALLBACK_IR.fps)}
      defaultProps={{ ir: FALLBACK_IR } as MainProps}
      calculateMetadata={calculateMetadata}
    />
  );
};
