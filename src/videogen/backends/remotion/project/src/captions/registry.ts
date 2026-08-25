// The caption renderer registry: the TS half of the caption library (ADR 0010). Maps a caption
// style `id` to the React component that paints it. `Main.tsx` dispatches a `text` layer here by its
// `style` id -- the single point where the backend branches on a style name. The registered id set
// must stay in sync with the Python caption style registry (the same ids on both sides); an id on
// one side but not the other is a defect (ADR 0010).
//
// pill / word-bold / kinetic are the original generic karaoke look -- three ids mapping to the one
// GenericCaption component, configured by the per-layer params the Python side bakes in. `title` is
// the text-hook overlay's own renderer (not a caption) sharing the dispatch path.

import { GenericCaption } from "./GenericCaption";
import { HighlightCaptions } from "./HighlightCaptions";
import { TikTokCaption } from "./TikTokCaption";
import { TitleCaption } from "./TitleCaption";
import type { CaptionRenderer } from "./types";

const REGISTRY: Record<string, CaptionRenderer> = {
  pill: GenericCaption,
  "word-bold": GenericCaption,
  kinetic: GenericCaption,
  "highlight-box": HighlightCaptions,
  tiktok: TikTokCaption,
  title: TitleCaption,
};

// The fallback for an unknown id: paint with the generic caption renderer rather than crash or blank,
// so a newer document (a style id this backend has not learned) still shows its text (ADR 0010's
// "unknown id hits a safe fallback, never a crash").
export const FALLBACK_CAPTION_RENDERER: CaptionRenderer = GenericCaption;

// The set of registered caption renderer ids -- exported so the boundary stays trivially inspectable
// against the Python registry's ids (the cross-side sync invariant, ADR 0010).
export const CAPTION_RENDERER_IDS: readonly string[] = Object.keys(REGISTRY);

// Resolve a caption style id to its renderer, falling back safely on an unknown id.
export function resolveCaptionRenderer(id: string): CaptionRenderer {
  return REGISTRY[id] ?? FALLBACK_CAPTION_RENDERER;
}
