// Shared prop types for all motion-graphics compositions.
// Same structural pattern as stat_viz/types.ts — Python MotionGraphicsRenderer merges
// data params + StyleBrief into a flat props dict matching these interfaces.

export interface MgBaseProps {
  background: string;
  primary: string;
  accent: string;
  accent2: string;
  fontFamily: string;
  fps: number;
  duration_s: number;
}

// Animated headline card: big text + optional subtext. animation_style controls the entrance.
export interface MgTitleCardProps extends MgBaseProps {
  headline: string;
  subtext: string;
  animation_style: "spring" | "fade" | "slide_up";
}

// Lower-third info bar: slides in from left, showing a name + role/label.
export interface MgLowerThirdProps extends MgBaseProps {
  name: string;
  role: string;
}

// CTA end card: full-screen closing panel with headline + subtext + CTA line.
export interface MgCtaCardProps extends MgBaseProps {
  headline: string;
  subtext: string;
  cta: string;
}

// Word-by-word kinetic text reveal — best for hooks and key statements.
export interface MgKineticTextProps extends MgBaseProps {
  text: string;
  animation_style: "word_spring" | "typewriter" | "glitch";
  font_size: number;
}

export function mgMetadata(fps: number, duration_s: number) {
  return {
    width: 1080,
    height: 1920,
    fps,
    durationInFrames: Math.max(1, Math.round(duration_s * fps)),
  };
}
