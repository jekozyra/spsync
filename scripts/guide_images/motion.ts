/**
 * Easing curves and numeric helpers for the guide animations.
 *
 * The curves follow the emil-design-eng motion rules: a strong ease-out for elements that enter or
 * leave, and a strong ease-in-out for elements that move on screen.
 */

export type EaseName = "out" | "inOut" | "move" | "linear";
export type Easing = (progress: number) => number;

const BISECTION_STEPS = 40;

/** A CSS cubic-bezier() curve: the eased value at a time from 0 to 1. */
function cubicBezier(x1: number, y1: number, x2: number, y2: number): Easing {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const curveX = (t: number) => ((ax * t + bx) * t + cx) * t;
  const curveY = (t: number) => ((ay * t + by) * t + cy) * t;

  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;

    let low = 0;
    let high = 1;
    let t = x;

    for (let step = 0; step < BISECTION_STEPS; step++) {
      if (curveX(t) < x) low = t;
      else high = t;
      t = (low + high) / 2;
    }

    return curveY(t);
  };
}

export const EASE: Record<EaseName, Easing> = {
  out: cubicBezier(0.23, 1, 0.32, 1),
  inOut: cubicBezier(0.77, 0, 0.175, 1),
  // A softer ease-in-out for the pointer, so that long moves do not look like jumps.
  move: cubicBezier(0.45, 0, 0.2, 1),
  linear: (x) => x,
};

export function clamp(x: number): number {
  return Math.max(0, Math.min(1, x));
}

export function lerp(from: number, to: number, progress: number): number {
  return from + (to - from) * progress;
}

export function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
