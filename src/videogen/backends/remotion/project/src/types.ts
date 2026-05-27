// TypeScript mirror of videogen's neutral render IR (kernel/ir.py). The Python side serializes an
// IR to JSON and passes it as Remotion --props; these types describe what arrives. The backend
// dispatches on the three layer kinds (media | text | audio) and never on overlay types, so the
// only Remotion code in the system lives under this project (ADR 0002).

export type Easing = "linear" | "ease_in" | "ease_out" | "ease_in_out";

export interface Keyframe {
  t: number; // absolute seconds
  value: number;
  easing: Easing;
}

// A possibly-animated scalar; a single keyframe means a constant value.
export interface Value {
  keyframes: Keyframe[];
}

export interface Transform {
  scale?: Value | null;
  translate_x?: Value | null;
  translate_y?: Value | null;
}

export interface TextRun {
  text: string;
  emphasis: boolean;
}

// Compiled visual properties of a caption. The compiler bakes the style (pill | word-bold |
// kinetic) into these fields, so the component paints from data and never branches on style name.
export interface TextStyle {
  font_size: number; // px at the IR canvas scale
  font_weight: number;
  color: string; // CSS color
  background?: string | null; // pill fill; null/absent = no pill
  border_radius: number; // px
  padding_x: number; // px
  padding_y: number; // px
}

interface LayerBase {
  start: number; // absolute seconds
  end: number;
  z: number;
  opacity: Value;
  transform?: Transform | null;
}

export interface MediaLayer extends LayerBase {
  kind: "media";
  src: string; // staticFile name (Python stages the asset into the public dir)
  in?: number | null; // source in-point; null this phase
}

export interface TextLayer extends LayerBase {
  kind: "text";
  runs: TextRun[];
  style: string; // provenance only; the component never branches on it
  props: TextStyle; // the visual props the component paints from
}

export interface AudioLayer extends LayerBase {
  kind: "audio";
  src: string;
  in?: number | null;
}

export type Layer = MediaLayer | TextLayer | AudioLayer;

export interface IR {
  width: number;
  height: number;
  fps: number;
  duration: number; // seconds; set by the voiceover (master clock)
  layers: Layer[];
}

// A `type` alias (not an interface) so it satisfies Remotion's `Record<string, unknown>` prop
// constraint -- interfaces lack the implicit index signature that constraint requires.
export type MainProps = {
  ir: IR;
};
