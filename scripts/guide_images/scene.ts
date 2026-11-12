/**
 * The scene runner. A scene file calls `scene()` once, and the renderer calls `window.renderAt(ms)`
 * for each frame.
 *
 * renderAt(ms): baseState --init--> State --replay actions up to ms--> State --views--> stage HTML
 *                                                                                 `--> pointer position
 *
 * A frame depends only on `ms`, so the renderer can seek to any time. The loop of a GIF cuts back to
 * the first frame with no fade: a fade of the full stage changes every pixel of each frame and about
 * doubles the file size.
 */
import { clamp, escapeHtml, lerp } from "./motion.ts";
import { Script } from "./script.ts";
import { baseState, type AppName, type Point, type State, type Target } from "./state.ts";
import { APP_VIEWS, POINTER_SVG } from "./views.ts";

// A short hold on the first frame, so the reader sees the start state before anything moves.
const LEAD_IN_MS = 320;
const PRESS_SCALE = 0.03;
const POINTER_PRESS_SCALE = 0.1;
const POINTER_TIP_PX = 2;
const MAX_POINTER_OFFSET_PX = 60;
const MIN_BLUR_PX = 0.05;

export interface SceneDefinition<S extends State> {
  /** How long the last frame stays before the loop starts again. */
  holdEndMs: number;
  init: (st: State) => S;
  script: (s: Script<S>) => void;
  /** CSS for the position of an app window, such as `inset:30px 40px`. */
  geometry?: Partial<Record<AppName, string>>;
  /** Extra HTML inside the Obsidian window, such as the settings dialog. */
  overlay?: (st: S) => string;
}

declare global {
  interface Window {
    renderAt: (ms: number) => void;
    sceneDurationMs: number;
    sceneStaticAtMs: number;
  }
}

// The last position of each pointer target. A move can start at an element that is gone from the
// current frame; the renderer draws frames in order, so the cache holds its last position.
const targetPositions = new Map<string, Point>();

function resolveTarget(target: Target | null, root: HTMLElement): Point | null {
  if (target === null) return null;
  if (typeof target !== "string") return target;

  const element = root.querySelector(`[data-id="${target}"]`);

  if (element) {
    const box = element.getBoundingClientRect();
    const position = { x: box.left + Math.min(box.width / 2, MAX_POINTER_OFFSET_PX), y: box.top + box.height / 2 };
    targetPositions.set(target, position);

    return position;
  }

  return targetPositions.get(target) ?? null;
}

function windowsHtml<S extends State>(st: S, definition: SceneDefinition<S>): string {
  const overlay = definition.overlay ? definition.overlay(st) : "";

  return st.order
    .map((app) => {
      const layer = st.layers[app];

      if (!layer || layer.o <= 0) return "";

      const view = APP_VIEWS[app];
      const blur = layer.blur > MIN_BLUR_PX ? `filter:blur(${layer.blur}px);` : "";
      const style = `${definition.geometry?.[app] ?? ""};opacity:${layer.o};transform:scale(${layer.s});${blur}`;

      return `<div class="win ${view.className}" style="${style}">${view.render(st, overlay)}</div>`;
    })
    .join("");
}

function placePointer(st: State, root: HTMLElement): void {
  const pointer = root.querySelector<SVGElement>("#pointer");
  const to = resolveTarget(st.pointer.to, root);
  const from = resolveTarget(st.pointer.from, root) ?? to;

  if (!pointer) return;

  if (!to || !from || st.pointer.o <= 0) {
    pointer.style.display = "none";

    return;
  }

  const x = lerp(from.x, to.x, st.pointer.p);
  const y = lerp(from.y, to.y, st.pointer.p);
  const scale = st.press ? 1 - POINTER_PRESS_SCALE * st.press.amount : 1;
  pointer.style.transform = `translate(${x - POINTER_TIP_PX}px, ${y - POINTER_TIP_PX}px) scale(${scale})`;
  pointer.style.opacity = String(st.pointer.o);
}

export function scene<S extends State>(definition: SceneDefinition<S>): void {
  const script = new Script<S>();
  definition.script(script);
  const total = LEAD_IN_MS + script.endMs + definition.holdEndMs;
  const stage = document.getElementById("stage");

  if (!stage) throw new Error("stage.html has no #stage element.");

  window.sceneDurationMs = total;
  window.sceneStaticAtMs = total - 1;
  window.renderAt = (ms) => {
    const st = definition.init(baseState());
    const local = ms - LEAD_IN_MS;

    for (const action of script.actions) {
      if (local < action.start) continue;

      const raw = action.durationMs ? clamp((local - action.start) / action.durationMs) : 1;
      action.apply(st, action.ease(raw), raw * action.durationMs);
    }

    const key = st.key
      ? `<div class="keychip" style="opacity:${st.key.o};transform:translate(-50%,${st.key.y}px)">${escapeHtml(st.key.label)}</div>`
      : "";
    stage.innerHTML = `<div id="scene">${windowsHtml(st, definition)}${key}${POINTER_SVG}</div>`;

    if (st.press) {
      const pressed = stage.querySelector<HTMLElement>(`[data-id="${st.press.id}"]`);

      if (pressed) pressed.style.transform = `scale(${1 - PRESS_SCALE * st.press.amount})`;
    }

    placePointer(st, stage);
  };
  window.renderAt(0);
}
