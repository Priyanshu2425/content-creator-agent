// The TS half of the caption library (ADR 0010). A caption renderer is a React component the IR
// interpreter dispatches a `text` layer to, keyed by the layer's `style` id through the registry in
// `registry.ts`. This is the single point where the Remotion backend branches on a style name; every
// other layer kind stays neutral (ADR 0002, amended by ADR 0010 for captions only).

import type React from "react";
import type { TextLayer } from "../types";

// Every caption renderer receives the same shape: the text layer (its runs + typed params), and the
// absolute timeline frame the layer starts at, so the renderer can drive the karaoke highlight and
// sample the opacity/scale tracks with the shared sampler (the pop-in rides those tracks, not code).
export interface CaptionRendererProps {
  layer: TextLayer;
  from: number;
}

export type CaptionRenderer = React.FC<CaptionRendererProps>;
