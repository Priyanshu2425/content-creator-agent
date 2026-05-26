// Remotion CLI config. Stills render as PNG (lossless, good for the non-black frame assertion);
// video image format stays JPEG for speed. The IR drives all per-render metadata (width, height,
// fps, duration) via calculateMetadata in src/Root.tsx, so nothing dimension-specific lives here.
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setStillImageFormat("png");
