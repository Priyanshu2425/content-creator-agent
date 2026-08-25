// Loads "TheBoldFont" -- the heavy display face Remotion's TikTok captions template ships as a
// bundled asset. It is not a Google Font, so (unlike the rest of the project's type) it cannot come
// through @remotion/google-fonts; the .ttf is bundled in the Remotion public dir
// (public/fonts/theboldfont.ttf) and loaded here once at import via the FontFace API. The render is
// held with delayRender until the face is ready so no frame paints the fallback. A missing/old asset
// must never wedge a render, so a load failure falls back to the CSS sans stack instead of hanging.

import { continueRender, delayRender, staticFile } from "remotion";

export const THE_BOLD_FONT = "TheBoldFont";

const handle = delayRender("Loading TheBoldFont");
const face = new FontFace(
  THE_BOLD_FONT,
  `url(${staticFile("fonts/theboldfont.ttf")}) format("truetype")`,
);
face
  .load()
  .then((loaded) => {
    document.fonts.add(loaded);
    continueRender(handle);
  })
  .catch((err) => {
    console.error("TheBoldFont failed to load; falling back to the sans stack.", err);
    continueRender(handle);
  });
