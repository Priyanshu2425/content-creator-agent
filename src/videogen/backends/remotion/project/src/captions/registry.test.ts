// Lightweight test of the caption renderer registry lookup + fallback (ADR 0010). The project ships
// no test runner (only `tsc`), so this is a self-contained script: run it with a TS-aware node
// (`npx tsx src/captions/registry.test.ts`) or simply typecheck it with `tsc --noEmit`. It asserts
// the two registry guarantees: a known id resolves to its component, and an unknown id falls back
// safely (never undefined / a crash). It also pins the registered id set so the cross-side sync with
// the Python caption style registry stays trivially inspectable.

import { GenericCaption } from "./GenericCaption";
import { HighlightCaptions } from "./HighlightCaptions";
import { TitleCaption } from "./TitleCaption";
import {
  CAPTION_RENDERER_IDS,
  FALLBACK_CAPTION_RENDERER,
  resolveCaptionRenderer,
} from "./registry";

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(`caption registry test failed: ${msg}`);
}

// Known ids resolve to their components.
assert(resolveCaptionRenderer("pill") === GenericCaption, "pill -> GenericCaption");
assert(resolveCaptionRenderer("word-bold") === GenericCaption, "word-bold -> GenericCaption");
assert(resolveCaptionRenderer("kinetic") === GenericCaption, "kinetic -> GenericCaption");
assert(
  resolveCaptionRenderer("highlight-box") === HighlightCaptions,
  "highlight-box -> HighlightCaptions",
);
assert(resolveCaptionRenderer("title") === TitleCaption, "title -> TitleCaption");

// An unknown id falls back safely -- a real component, never undefined.
const unknown = resolveCaptionRenderer("does-not-exist");
assert(unknown === FALLBACK_CAPTION_RENDERER, "unknown id -> fallback renderer");
assert(typeof unknown === "function", "fallback is a renderable component");

// The registered id set is the source of truth the Python side must match (pill / word-bold /
// kinetic are caption styles; title is the text-hook overlay's renderer sharing the dispatch).
const ids = [...CAPTION_RENDERER_IDS].sort();
assert(
  JSON.stringify(ids) ===
    JSON.stringify(["highlight-box", "kinetic", "pill", "title", "word-bold"]),
  `registered ids: ${ids.join(", ")}`,
);

// eslint-disable-next-line no-console
console.log("caption registry test: OK", { registeredIds: ids });
