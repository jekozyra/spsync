/* Step 9: run Check setup, fix the failed check, and run Check setup again. */
import { clamp, EASE, escapeHtml } from "../motion.ts";
import { scene } from "../scene.ts";
import type { Script } from "../script.ts";
import { withLinkedNote, type State } from "../state.ts";

// The checks of `run_checks` in src/spsync/doctor.py, as `SetupModal` in main.ts shows them.
interface Check {
  ok: boolean;
  name: string;
  detail: string;
  fix?: string;
}

const AUTOMATION_FIX =
  "Open System Settings > Privacy & Security > Automation. Under the app that runs spsync, such as Obsidian or Terminal, turn on Microsoft Word.";
const AUTHOR_DETAIL =
  'Alex Example, from your macOS full name. Change it with spsync mode --author "Your Name", or with the "Author name" setting of the Obsidian plugin.';

function checks(automationAllowed: boolean): Check[] {
  return [
    { ok: true, name: "CLI version", detail: "spsync 0.1.0" },
    { ok: true, name: "OneDrive folder", detail: "/Users/alex/Library/CloudStorage/OneDrive-SampleOrg" },
    { ok: true, name: "Word for Mac", detail: "/Applications/Microsoft Word.app" },
    automationAllowed
      ? { ok: true, name: "Automation permission", detail: "spsync can control Word." }
      : { ok: false, name: "Automation permission", detail: "macOS does not let spsync control Word.", fix: AUTOMATION_FIX },
    { ok: true, name: "Author name", detail: AUTHOR_DETAIL },
  ];
}

const ROW_STAGGER_MS = 50;
const ROW_IN_MS = 220;
const ROW_RISE_PX = 4;
const CHECK_RUN_MS = 1300;
const CHECK_COUNT = checks(false).length;

type SetupState = State & { automationAllowed: boolean; rowsMs: number };

function setupModal(st: SetupState): string {
  const rows = checks(st.automationAllowed);
  const title = rows.every((c) => c.ok) ? "Setup is complete" : "Setup needs attention";
  const html = rows
    .map((c, k) => {
      const p = EASE.out(clamp((st.rowsMs - k * ROW_STAGGER_MS) / ROW_IN_MS));
      const fix = c.fix ? `<div class="fx">Fix: ${escapeHtml(c.fix)}</div>` : "";

      return `<div class="check" style="opacity:${p};transform:translateY(${(1 - p) * ROW_RISE_PX}px)"><strong class="${c.ok ? "pass" : "fail"}">${c.ok ? "Pass" : "Fail"}: ${escapeHtml(c.name)}</strong><div class="dt">${escapeHtml(c.detail)}</div>${fix}</div>`;
    })
    .join("");

  return `<div class="mtitle">${title}</div>${html}`;
}

function checkSetup(s: Script<SetupState>): void {
  s.palette("check setup", "Check setup");
  s.notice("Checking setup. Word can start in the background.", { sticky: true, id: "checking" }).wait(CHECK_RUN_MS);
  s.hideNotice("checking");
  s.set((st) => {
    st.rowsMs = 0;
  });
  s.span(
    ROW_IN_MS + CHECK_COUNT * ROW_STAGGER_MS,
    (st, _p, ms) => {
      st.rowsMs = ms;
    },
    "linear",
    { parallel: true },
  );
  s.modal(setupModal, "width:470px;top:47%");
}

scene<SetupState>({
  holdEndMs: 2200,
  geometry: { sys: "inset:40px 60px 30px 80px" },
  init: (st) => ({ ...withLinkedNote(st), automation: { toggle: 0 }, automationAllowed: false, rowsMs: 0 }),
  script: (s) => {
    s.wait(500);
    checkSetup(s);
    s.wait(3400);
    s.key("esc").wait(100).closeModal().wait(300);

    s.switchTo("sys").wait(400);
    s.pointerAt({ x: 420, y: 380 }).move("word-toggle", 650).click("word-toggle");
    s.span(
      200,
      (st, p) => {
        if (st.automation) st.automation.toggle = p;
      },
      "out",
    ).wait(700);
    s.hidePointer().set((st) => {
      st.automationAllowed = true;
    });

    s.switchTo("obsidian").wait(400);
    checkSetup(s);
    s.wait(600);
  },
});
