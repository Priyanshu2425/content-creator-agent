// Shared prop types for all stat-viz compositions.
// The Python StatVizRenderer merges data params + StyleBrief into a flat props dict; these
// interfaces describe what arrives in the composition's defaultProps / calculateMetadata.

export interface StyleBriefProps {
  background: string;
  primary: string;
  accent: string;
  fontFamily: string;
}

// Every stat-viz composition also receives fps and duration_s so its calculateMetadata can set
// the correct durationInFrames without relying on a full IR.
export interface StatVizBaseProps extends StyleBriefProps {
  fps: number;
  duration_s: number;
}

export interface StatVizCounterProps extends StatVizBaseProps {
  value: number;
  unit: string;
  label: string;
}

export interface StatVizBarProps extends StatVizBaseProps {
  label_a: string;
  value_a: number;
  label_b: string;
  value_b: number;
  unit: string;
}

export interface StatVizGaugeProps extends StatVizBaseProps {
  value: number;
  max: number;
  unit: string;
  label: string;
}

export interface StatVizBeforeAfterProps extends StatVizBaseProps {
  label_a: string;
  value_a: string;
  label_b: string;
  value_b: string;
}

export interface StatVizRatioProps extends StatVizBaseProps {
  numerator: number;
  denominator: number;
  label: string;
}

// Shared calculateMetadata helper: derive durationInFrames from duration_s * fps.
// Call inside each composition's calculateMetadata arrow function.
export function statVizMetadata(fps: number, duration_s: number) {
  return {
    width: 1080,
    height: 1920,
    fps,
    durationInFrames: Math.max(1, Math.round(duration_s * fps)),
  };
}
