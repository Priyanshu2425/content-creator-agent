// Remotion entry point: the file the CLI bundles. Passed to `npx remotion render|still` by the
// Python RemotionBackend.
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
