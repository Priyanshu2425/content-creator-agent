// Registers "Main" (the full-video IR-driven composition) and the five stat-viz compositions
// (StatVizCounter, StatVizBar, StatVizGauge, StatVizBeforeAfter, StatVizRatio). The stat-viz
// compositions accept simple props (data + StyleBrief) rather than a full IR; their
// calculateMetadata derives durationInFrames from the duration_s + fps props the Python layer
// passes, using the shared statVizMetadata helper from stat_viz/types.ts.

import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { Main } from "./Main";
import type { IR, MainProps } from "./types";
import { StatVizCounter } from "./stat_viz/Counter";
import { StatVizBar } from "./stat_viz/Bar";
import { StatVizGauge } from "./stat_viz/Gauge";
import { StatVizBeforeAfter } from "./stat_viz/BeforeAfter";
import { StatVizRatio } from "./stat_viz/Ratio";
import {
  statVizMetadata,
  type StatVizCounterProps,
  type StatVizBarProps,
  type StatVizGaugeProps,
  type StatVizBeforeAfterProps,
  type StatVizRatioProps,
} from "./stat_viz/types";

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

const _STAT_VIZ_FALLBACK_FPS = 30;
const _STAT_VIZ_FALLBACK_DURATION = 2;

export const RemotionRoot: React.FC = () => {
  return (
    <>
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

      <Composition
        id="StatVizCounter"
        component={StatVizCounter}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ value: 40, unit: "%", label: "Growth", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", fontFamily: "Arial" } as StatVizCounterProps}
        calculateMetadata={({ props }) => statVizMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="StatVizBar"
        component={StatVizBar}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ label_a: "Before", value_a: 20, label_b: "After", value_b: 80, unit: "%", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", fontFamily: "Arial" } as StatVizBarProps}
        calculateMetadata={({ props }) => statVizMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="StatVizGauge"
        component={StatVizGauge}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ value: 3, max: 10, unit: "$M", label: "Funding Goal", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", fontFamily: "Arial" } as StatVizGaugeProps}
        calculateMetadata={({ props }) => statVizMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="StatVizBeforeAfter"
        component={StatVizBeforeAfter}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ label_a: "Before", value_a: "3 hours", label_b: "After", value_b: "10 minutes", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", fontFamily: "Arial" } as StatVizBeforeAfterProps}
        calculateMetadata={({ props }) => statVizMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="StatVizRatio"
        component={StatVizRatio}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ numerator: 1, denominator: 3, label: "churn within 90 days", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", fontFamily: "Arial" } as StatVizRatioProps}
        calculateMetadata={({ props }) => statVizMetadata(props.fps, props.duration_s)}
      />
    </>
  );
};
