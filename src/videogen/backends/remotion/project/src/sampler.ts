// Keyframe sampler: evaluate a Value's animated track at a given frame.
//
// This is the per-frame evaluator the full system relies on. Phase 2 only ever feeds it constant
// tracks (a single keyframe, or none), so it runs its trivial path here -- but it implements real
// piecewise interpolation now so Phase 3's kinetic captions plug into already-exercised machinery.

import { Easing as RemotionEasing, interpolate } from "remotion";
import type { Easing, Value } from "./types";

type EasingFn = (input: number) => number;

const EASING_FNS: Record<Easing, EasingFn> = {
  linear: (x) => x,
  ease_in: RemotionEasing.in(RemotionEasing.ease),
  ease_out: RemotionEasing.out(RemotionEasing.ease),
  ease_in_out: RemotionEasing.inOut(RemotionEasing.ease),
};

// Sample `value` at absolute `frame`. `fallback` is returned when the track is absent.
export function sample(
  value: Value | null | undefined,
  frame: number,
  fps: number,
  fallback: number,
): number {
  if (!value || value.keyframes.length === 0) {
    return fallback;
  }
  const kfs = value.keyframes;
  if (kfs.length === 1) {
    return kfs[0].value; // constant path -- the only path exercised this phase
  }

  const t = frame / fps;
  if (t <= kfs[0].t) {
    return kfs[0].value;
  }
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (t >= a.t && t <= b.t) {
      return interpolate(t, [a.t, b.t], [a.value, b.value], {
        easing: EASING_FNS[b.easing] ?? EASING_FNS.linear,
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
  }
  return kfs[kfs.length - 1].value;
}
