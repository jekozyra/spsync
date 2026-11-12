/**
 * The timeline of a scene: a list of actions, each with a start time, a duration, and an easing.
 *
 * Each method appends one or more actions and moves the cursor to their end, unless the action runs
 * in parallel. An action receives the frame state and its eased progress from 0 to 1. Actions only
 * write state; the views turn the state into HTML.
 *
 * Motion rules: the command palette opens and closes with no animation, because people open it from
 * the keyboard many times a day. Modals and notices enter with ease-out and leave faster than they
 * enter. The pointer moves with ease-in-out.
 */
import { EASE, lerp, type EaseName, type Easing } from "./motion.ts";
import { SYNCED_STATUS, type AppName, type Note, type State, type Target } from "./state.ts";

const TYPE_CHARS_PER_SECOND = 17;
const BACKSPACE_CHARS_PER_SECOND = 22;
const MS_PER_SECOND = 1000;

const KEY_IN_MS = 120;
const KEY_HOLD_MS = 650;
const KEY_OUT_MS = 140;
const KEY_RISE_PX = 6;

const NOTICE_IN_MS = 220;
const NOTICE_OUT_MS = 150;
const NOTICE_HOLD_MS = 2600;
const SYNC_NOTICE_HOLD_MS = 3400;
const NOTICE_ENTER_PX = -8;
const NOTICE_EXIT_PX = -6;

export const MODAL_IN_MS = 200;
const MODAL_OUT_MS = 140;
const MODAL_ENTER_SCALE = 0.96;
const MODAL_EXIT_SCALE = 0.98;

const PRESS_MS = 160;
const PRESS_DOWN_FRACTION = 0.35;
const POINTER_MOVE_MS = 620;
const POINTER_FADE_MS = 200;

const SWITCH_MS = 340;
const SWITCH_ENTER_SCALE = 0.97;
const SWITCH_BLUR_PX = 4;

const SCROLL_MS = 520;
const PALETTE_OPEN_DELAY_MS = 80;
const PALETTE_READ_MS = 350;
const PALETTE_PICK_MS = 650;
const PALETTE_CLOSE_DELAY_MS = 120;
const SYNC_RUN_MS = 900;

const PLUGIN_COMMAND_PREFIX = "SharePoint Sync: ";

interface Action<S> {
  start: number;
  durationMs: number;
  ease: Easing;
  apply: (st: S, progress: number, elapsedMs: number) => void;
}

interface SpanOptions {
  /** Start at the cursor, but leave the cursor where it is. */
  parallel?: boolean;
}

/** Insert typed text at the caret. A newline in the text splits the line. */
function insertText(note: Note, chunk: string): void {
  if (!chunk || !note.cur) return;

  const { line, ch } = note.cur;
  const current = note.lines[line];
  const parts = (current.slice(0, ch) + chunk).split("\n");
  const last = parts.length - 1;
  const caretCh = parts[last].length;
  parts[last] += current.slice(ch);
  note.lines.splice(line, 1, ...parts);
  note.cur = { line: line + last, ch: caretCh };
}

function typingMs(text: string, charsPerSecond: number): number {
  return (text.length / charsPerSecond) * MS_PER_SECOND;
}

export class Script<S extends State> {
  readonly actions: Action<S>[] = [];
  private cursor = 0;

  /** The end of the last action. */
  get endMs(): number {
    return Math.max(this.cursor, ...this.actions.map((a) => a.start + a.durationMs));
  }

  span(
    durationMs: number,
    apply: (st: S, progress: number, elapsedMs: number) => void,
    ease: EaseName = "linear",
    { parallel = false }: SpanOptions = {},
  ): this {
    this.actions.push({ start: this.cursor, durationMs, ease: EASE[ease], apply });

    if (!parallel) this.cursor += durationMs;

    return this;
  }

  set(apply: (st: S) => void): this {
    return this.span(0, (st) => apply(st));
  }

  wait(ms: number): this {
    this.cursor += ms;

    return this;
  }

  /** Show a key press, such as "⌘ P", at the bottom of the stage. Runs in parallel. */
  key(label: string): this {
    return this.span(
      KEY_IN_MS + KEY_HOLD_MS + KEY_OUT_MS,
      (st, _p, ms) => {
        let o = 1;

        if (ms < KEY_IN_MS) o = EASE.out(ms / KEY_IN_MS);
        else if (ms > KEY_IN_MS + KEY_HOLD_MS) o = 1 - EASE.out((ms - KEY_IN_MS - KEY_HOLD_MS) / KEY_OUT_MS);

        st.key = o > 0 ? { label, o, y: (1 - o) * KEY_RISE_PX } : null;
      },
      "linear",
      { parallel: true },
    );
  }

  /** Show an Obsidian notice. A sticky notice stays until `hideNotice`. Runs in parallel. */
  notice(text: string, { holdMs = NOTICE_HOLD_MS, sticky = false, id = text } = {}): this {
    const total = sticky ? NOTICE_IN_MS : NOTICE_IN_MS + holdMs + NOTICE_OUT_MS;

    return this.span(
      total,
      (st, _p, ms) => {
        let o = 1;
        let y = 0;

        if (ms < NOTICE_IN_MS) {
          o = EASE.out(ms / NOTICE_IN_MS);
          y = (1 - o) * NOTICE_ENTER_PX;
        } else if (!sticky && ms >= NOTICE_IN_MS + holdMs) {
          const out = EASE.out((ms - NOTICE_IN_MS - holdMs) / NOTICE_OUT_MS);
          o = 1 - out;
          y = out * NOTICE_EXIT_PX;
        }

        st.notices = st.notices.filter((n) => n.id !== id);

        if (o > 0) st.notices.push({ id, text, o, y });
      },
      "linear",
      { parallel: true },
    );
  }

  hideNotice(id: string): this {
    return this.span(
      NOTICE_OUT_MS,
      (st, p) => {
        const notice = st.notices.find((n) => n.id === id);

        if (!notice) return;

        notice.o = 1 - p;
        notice.y = NOTICE_EXIT_PX * p;

        if (p >= 1) st.notices = st.notices.filter((n) => n.id !== id);
      },
      "out",
      { parallel: true },
    );
  }

  /** Open a centered modal. `render` reads the frame state, so typed text shows as it is typed. */
  modal(render: (st: S) => string, style = ""): this {
    this.set((st) => {
      st.modal = { o: 0, s: MODAL_ENTER_SCALE, style, render: () => render(st) };
    });

    return this.span(
      MODAL_IN_MS,
      (st, p) => {
        if (!st.modal) return;

        st.modal.o = p;
        st.modal.s = lerp(MODAL_ENTER_SCALE, 1, p);
      },
      "out",
    );
  }

  closeModal(): this {
    this.span(
      MODAL_OUT_MS,
      (st, p) => {
        if (!st.modal) return;

        st.modal.o = 1 - p;
        st.modal.s = lerp(1, MODAL_EXIT_SCALE, p);
      },
      "out",
    );

    return this.set((st) => {
      st.modal = null;
    });
  }

  /** Type text into a field: `set` receives the field value before typing plus the typed part. */
  typeTo(get: (st: S) => string, set: (st: S, value: string) => void, text: string): this {
    return this.span(typingMs(text, TYPE_CHARS_PER_SECOND), (st, p) => {
      set(st, get(st) + text.slice(0, Math.round(p * text.length)));
    });
  }

  // ---- pointer ----

  /** Show the pointer at a target. */
  pointerAt(target: Target): this {
    this.set((st) => {
      st.pointer.from = target;
      st.pointer.to = target;
    });

    return this.span(
      POINTER_FADE_MS,
      (st, p) => {
        st.pointer.o = p;
      },
      "out",
      { parallel: true },
    );
  }

  move(target: Target, durationMs = POINTER_MOVE_MS): this {
    return this.span(
      durationMs,
      (st, p) => {
        st.pointer.from = st.pointer.to;
        st.pointer.to = target;
        st.pointer.p = p;
        st.pointer.o = 1;
      },
      "move",
    );
  }

  /** Press and release the element with this `data-id`. */
  click(id: string): this {
    return this.span(PRESS_MS, (st, p) => {
      const amount = p < PRESS_DOWN_FRACTION ? p / PRESS_DOWN_FRACTION : 1 - (p - PRESS_DOWN_FRACTION) / (1 - PRESS_DOWN_FRACTION);
      st.press = p < 1 ? { id, amount } : null;
    });
  }

  hidePointer(): this {
    return this.span(
      POINTER_FADE_MS,
      (st, p) => {
        st.pointer.o = 1 - p;
      },
      "out",
      { parallel: true },
    );
  }

  // ---- apps ----

  /** Bring an app window to the front with a short crossfade. */
  switchTo(app: AppName): this {
    this.set((st) => {
      st.order = [...st.order.filter((a) => a !== app), app];
    });

    return this.span(
      SWITCH_MS,
      (st, p) => {
        st.layers[app] = { o: p, s: lerp(SWITCH_ENTER_SCALE, 1, p), blur: (1 - p) * SWITCH_BLUR_PX };
      },
      "out",
    );
  }

  // ---- Obsidian ----

  /** Open the command palette, type a query, and run a command. */
  palette(query: string, command: string, prefix = PLUGIN_COMMAND_PREFIX): this {
    this.key("⌘ P");
    this.wait(PALETTE_OPEN_DELAY_MS).set((st) => {
      st.prompt = { kind: "command", query: "", placeholder: "Select a command..." };
    });
    this.wait(PALETTE_READ_MS);
    this.typeTo(
      (st) => st.prompt?.query ?? "",
      (st, value) => {
        if (st.prompt) st.prompt.query = value;
      },
      query,
    );
    this.set((st) => {
      if (st.prompt) st.prompt.pick = prefix + command;
    });
    this.wait(PALETTE_PICK_MS).key("↩").wait(PALETTE_CLOSE_DELAY_MS);

    return this.set((st) => {
      st.prompt = null;
    });
  }

  /** Run a sync command, and show the CLI result in a notice. */
  sync(result: string, { command = "Sync this note", query = "sync this" } = {}): this {
    this.palette(query, command);
    this.status("SharePoint: syncing Project plan...").wait(SYNC_RUN_MS);
    this.notice(result, { holdMs: SYNC_NOTICE_HOLD_MS });

    return this.status(SYNCED_STATUS);
  }

  status(text: string): this {
    return this.set((st) => {
      st.status = text;
    });
  }

  /** Put the caret in the note. Without `ch`, the caret goes to the end of the line. */
  caret(line: number, ch?: number): this {
    return this.set((st) => {
      if (!st.note) return;

      st.note.cur = { line, ch: ch ?? st.note.lines[line].length };
      st.note.sel = null;
    });
  }

  noCaret(): this {
    return this.set((st) => {
      if (st.note) st.note.cur = null;
    });
  }

  typeNote(text: string): this {
    return this.span(typingMs(text, TYPE_CHARS_PER_SECOND), (st, p) => {
      if (st.note) insertText(st.note, text.slice(0, Math.round(p * text.length)));
    });
  }

  backspace(count: number): this {
    return this.span(typingMs(" ".repeat(count), BACKSPACE_CHARS_PER_SECOND), (st, p) => {
      if (!st.note?.cur) return;

      const deleted = Math.round(p * count);
      const { line, ch } = st.note.cur;
      const text = st.note.lines[line];
      st.note.lines[line] = text.slice(0, ch - deleted) + text.slice(ch);
      st.note.cur = { line, ch: ch - deleted };
    });
  }

  selectLines(from: number, to: number): this {
    return this.set((st) => {
      if (!st.note) return;

      st.note.sel = { from, to };
      st.note.cur = { line: to, ch: st.note.lines[to].length };
    });
  }

  deleteSelection(): this {
    return this.set((st) => {
      if (!st.note?.sel) return;

      const { from, to } = st.note.sel;
      st.note.lines.splice(from, to - from + 1);
      const line = Math.max(0, from - 1);
      st.note.sel = null;
      st.note.cur = { line, ch: st.note.lines[line].length };
    });
  }

  /** Scroll the note so that its top is `px` pixels above the editor top. */
  scrollTo(px: number): this {
    return this.span(
      SCROLL_MS,
      (st, p) => {
        st.scroll = lerp(st.scroll, px, p);
      },
      "inOut",
    );
  }
}
