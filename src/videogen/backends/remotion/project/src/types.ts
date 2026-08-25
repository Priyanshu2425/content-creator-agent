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
  start?: number | null; // word's spoken window (absolute seconds); null = static run
  end?: number | null;
}

// The `generic` caption renderer's visual params (ADR 0010), carried by a `text` layer as `params`.
// No longer a universal field: this is the param schema of the one generic renderer that pill /
// word-bold / kinetic configure. The backend dispatches the layer to a caption renderer by its
// `style` id (see captions/registry.ts) and that renderer paints from these fields.
export interface TextStyle {
  font_size: number; // px at the IR canvas scale
  font_weight: number;
  color: string; // CSS color
  background?: string | null; // pill fill; null/absent = no pill
  border_radius: number; // px
  padding_x: number; // px
  padding_y: number; // px
  highlight_color?: string | null; // active-word fill for karaoke runs; null/absent = no highlight
}

// The `highlight-box` caption renderer's visual params (ADR 0010). Distinct schema from the generic
// renderer's TextStyle: each renderer paints from its own fields. Words wrap in colored highlighter
// boxes with rotation jitter and a per-word spring pop driven by each run's spoken window.
export interface HighlightBoxStyle {
  font_size: number; // px at the IR canvas scale
  font_weight: number;
  text_color: string; // word text fill, CSS color
  box_colors: string[]; // highlighter box fills, cycled across words
  box_radius: number; // px
  padding_x: number; // px
  padding_y: number; // px
  rotation_jitter_deg: number; // max absolute per-box rotation
  pop_seconds: number; // per-word spring pop window; 0 = no pop
  pop_start_scale: number; // scale at the start of a word's pop
}

// The `tiktok` caption renderer's visual params (ADR 0010): a port of Remotion's TikTok captions
// template. Heavy text with a thick black stroke, the line pops in (scale + rise), and the word
// being spoken now is recoloured to `active_color`. Its own schema, distinct from TextStyle /
// HighlightBoxStyle -- the renderer owns the enter spring and the active-word highlight.
export interface TikTokStyle {
  font_size: number; // px at the IR canvas scale
  font_weight: number;
  color: string; // inactive word fill, CSS color
  active_color: string; // the word being spoken now, CSS color
  stroke_width: number; // px; black outline thickness (0 = no stroke)
  stroke_color: string; // outline colour, CSS color
  pop_seconds: number; // line enter-spring window; 0 = no pop
  pop_start_scale: number; // scale at the start of the enter
  pop_translate_y: number; // px the line rises from during the enter
}

interface LayerBase {
  start: number; // absolute seconds
  end: number;
  z: number;
  opacity: Value;
  transform?: Transform | null;
}

// A media layer's destination box, as normalized [0,1] fractions of the frame. The layout preset
// owns this geometry (split-h regions); absent/null means the whole frame.
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MediaLayer extends LayerBase {
  kind: "media";
  src: string; // staticFile name (Python stages the asset into the public dir)
  content: "video" | "image"; // paint as a clip or a still
  in?: number | null; // source in-point
  rect?: Rect | null; // destination box; null = full frame
  crop?: Rect | null; // source sub-rect to show (normalized); null = whole source (cover)
}

export interface TextLayer extends LayerBase {
  kind: "text";
  runs: TextRun[];
  // The caption style id, now authoritative: the backend dispatches this layer to the caption
  // renderer registered under it (ADR 0010). "title" is the text-hook overlay's renderer (not a
  // caption); pill / word-bold / kinetic are the generic karaoke renderer.
  style: string;
  // The renderer's typed params it paints from. Each caption renderer has its own param schema
  // (ADR 0010): generic (pill/word-bold/kinetic) → TextStyle, highlight-box → HighlightBoxStyle,
  // tiktok → TikTokStyle.
  params: TextStyle | HighlightBoxStyle | TikTokStyle;
}

export interface AudioLayer extends LayerBase {
  kind: "audio";
  src: string;
  in?: number | null;
}

// The opening text-hook (ADR 0013): a kernel-level singleton, always painted via the hook renderer
// (CenterHookCard). Carries semantic params (words + look), never an animation -- the renderer owns
// the cursor/click animation.
export interface HookLayer extends LayerBase {
  kind: "hook";
  text: string;
  text_color: string;
  box_color: string;
  brand: string;
  placement: "top" | "center";
}

export type Layer = MediaLayer | TextLayer | AudioLayer | HookLayer;

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
