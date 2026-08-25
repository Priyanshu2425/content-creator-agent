// Registers "Main" (the full-video IR-driven composition) and the five stat-viz compositions
// (StatVizCounter, StatVizBar, StatVizGauge, StatVizBeforeAfter, StatVizRatio). The stat-viz
// compositions accept simple props (data + StyleBrief) rather than a full IR; their
// calculateMetadata derives durationInFrames from the duration_s + fps props the Python layer
// passes, using the shared statVizMetadata helper from stat_viz/types.ts.

import React from "react";
import { CalculateMetadataFunction, Composition, staticFile } from "remotion";
import { Main } from "./Main";
import type { IR, MainProps } from "./types";
import { StatVizCounter } from "./stat_viz/Counter";
import { StatVizBar } from "./stat_viz/Bar";
import { StatVizGauge } from "./stat_viz/Gauge";
import { StatVizBeforeAfter } from "./stat_viz/BeforeAfter";
import { StatVizRatio } from "./stat_viz/Ratio";
import { ChazonCard, type ChazonCardProps } from "./brand_card/ChazonCard";
import { NormalizePoster, type NormalizePosterProps } from "./brand_card/NormalizePoster";
import { CenterHookCard, type CenterHookCardProps } from "./brand_card/CenterHookCard";
import {
  statVizMetadata,
  type StatVizCounterProps,
  type StatVizBarProps,
  type StatVizGaugeProps,
  type StatVizBeforeAfterProps,
  type StatVizRatioProps,
} from "./stat_viz/types";
import { MgTitleCard } from "./motion_graphics/TitleCard";
import { MgLowerThird } from "./motion_graphics/LowerThird";
import { MgCtaCard } from "./motion_graphics/CTACard";
import { MgKineticText } from "./motion_graphics/KineticText";
import {
  mgMetadata,
  type MgTitleCardProps,
  type MgLowerThirdProps,
  type MgCtaCardProps,
  type MgKineticTextProps,
} from "./motion_graphics/types";

const FALLBACK_IR: IR = {
  width: 1080,
  height: 1920,
  fps: 30,
  duration: 1,
  layers: [],
};

// seconds -> frames is fixed here: durationInFrames = round(duration * fps). The Python backend
// uses the same rule for the still frame index, so timing does not drift across the boundary.
//
// `videogen preview` stages a finished run's IR to public/preview-ir.json and opens Studio. The
// composition's default props carry the empty FALLBACK_IR, so when the incoming IR has no layers we
// try to load that staged preview IR and render it instead. A real `remotion render` passes a
// populated IR (layers present) and skips the fetch entirely.
const calculateMetadata: CalculateMetadataFunction<MainProps> = async ({ props }) => {
  let { ir } = props;
  if (ir.layers.length === 0) {
    try {
      const res = await fetch(staticFile("preview-ir.json"));
      if (res.ok) {
        const loaded = (await res.json()) as { ir?: IR };
        if (loaded.ir) ir = loaded.ir;
      }
    } catch {
      // No staged preview present -- keep the fallback (an empty 1-frame composition).
    }
  }
  return {
    props: { ir },
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

      <Composition
        id="ChazonCard"
        component={ChazonCard}
        width={1080}
        height={1350}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * 6}
        defaultProps={{ fps: _STAT_VIZ_FALLBACK_FPS, duration_s: 6 } as ChazonCardProps}
      />

      <Composition
        id="NormalizePoster"
        component={NormalizePoster}
        width={600}
        height={600}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * 4}
        defaultProps={{ fps: _STAT_VIZ_FALLBACK_FPS, duration_s: 4 } as NormalizePosterProps}
      />

      <Composition
        id="CenterHookCard"
        component={CenterHookCard}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * 3}
        defaultProps={{
          fps: _STAT_VIZ_FALLBACK_FPS,
          duration_s: 3,
          videoSrc: "smoke_host.mp4",
          hookText: "what if 12 year olds build the next AI startup?",
          textColor: "#0A0A0A",
          boxColor: "#FF6A00",
          brand: "buildspace labs",
        } as CenterHookCardProps}
      />

      {/* Motion Graphics compositions */}
      <Composition
        id="MgTitleCard"
        component={MgTitleCard}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ headline: "Title", subtext: "", animation_style: "spring", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", accent2: "#FFD700", fontFamily: "Arial" } as MgTitleCardProps}
        calculateMetadata={({ props }) => mgMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="MgLowerThird"
        component={MgLowerThird}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ name: "Speaker Name", role: "Role / Title", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", accent2: "#FFD700", fontFamily: "Arial" } as MgLowerThirdProps}
        calculateMetadata={({ props }) => mgMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="MgCtaCard"
        component={MgCtaCard}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ headline: "Headline", subtext: "", cta: "Follow for more", fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", accent2: "#000000", fontFamily: "Arial" } as MgCtaCardProps}
        calculateMetadata={({ props }) => mgMetadata(props.fps, props.duration_s)}
      />

      <Composition
        id="MgKineticText"
        component={MgKineticText}
        width={1080}
        height={1920}
        fps={_STAT_VIZ_FALLBACK_FPS}
        durationInFrames={_STAT_VIZ_FALLBACK_FPS * _STAT_VIZ_FALLBACK_DURATION}
        defaultProps={{ text: "Your message here", animation_style: "word_spring", font_size: 88, fps: _STAT_VIZ_FALLBACK_FPS, duration_s: _STAT_VIZ_FALLBACK_DURATION, background: "#0D0D0D", primary: "#FFFFFF", accent: "#FF6B35", accent2: "#FFD700", fontFamily: "Arial" } as MgKineticTextProps}
        calculateMetadata={({ props }) => mgMetadata(props.fps, props.duration_s)}
      />
    </>
  );
};
