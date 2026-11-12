/* Step 1: install BRAT, add jekozyra/spsync in BRAT, and wait for the CLI download. */
import { escapeHtml } from "../motion.ts";
import { scene } from "../scene.ts";
import { FILES, type State } from "../state.ts";

const NAV = ["General", "Editor", "Files and links", "Appearance", "Hotkeys", "Core plugins", "Community plugins"];
const COMMUNITY = "Community plugins";
const MIN_SEARCH_CHARS = 3;

interface Settings {
  nav: string;
  page: "" | "community" | "browse";
  query: string;
  picked: boolean;
  button: string;
  installed: string;
}

type InstallState = State & { settings: Settings | null; repo: string };

function communityPage(s: Settings): string {
  return `<h3>Community plugins</h3>
    <div class="srow"><div>Community plugins<div class="d">Find and install plugins that people in the community made.</div></div><span class="btn cta" data-id="browse">Browse</span></div>
    <div class="srow"><div>Installed plugins<div class="d">${s.installed || "No plugins installed."}</div></div></div>`;
}

function browsePage(s: Settings): string {
  const card =
    s.query.length >= MIN_SEARCH_CHARS
      ? `<div class="card${s.picked ? " on" : ""}" data-id="brat-card"><div class="n">BRAT</div><div class="a">By TfTHacker</div><div class="ds">Beta Reviewers Auto-update Tool: install and update plugins that are in beta.</div></div>`
      : "";
  const detail = s.picked
    ? `<div style="position:absolute;right:22px;top:58px;width:200px"><div style="font-weight:650;font-size:14px">BRAT</div><div style="color:#888;font-size:11px;margin:4px 0 10px">Version 1.x</div><span class="btn cta" data-id="install">${escapeHtml(s.button)}</span></div>`
    : "";

  return `<h3>Community plugins</h3><div class="field focus" style="width:240px">${escapeHtml(s.query)}<span class="caret"></span></div><div style="width:240px">${card}</div>${detail}`;
}

function settingsView(st: InstallState): string {
  const s = st.settings;

  if (!s) return "";

  const nav = '<div class="h">Options</div>' + NAV.map((n) => `<div class="i${n === s.nav ? " on" : ""}" data-id="nav-${n}">${n}</div>`).join("");
  const pane = s.page === "community" ? communityPage(s) : s.page === "browse" ? browsePage(s) : "";

  return `<div class="dim"></div><div class="settings"><div class="snav">${nav}</div><div class="spane">${pane}</div></div>`;
}

function blankSettings(): Settings {
  return { nav: "General", page: "", query: "", picked: false, button: "Install", installed: "" };
}

scene<InstallState>({
  holdEndMs: 1800,
  overlay: settingsView,
  init: (st) => ({ ...st, files: FILES, settings: null, repo: "" }),
  script: (s) => {
    // Settings opens from the keyboard, so it opens with no animation.
    s.wait(500).key("⌘ ,").wait(120);
    s.set((st) => {
      st.settings = blankSettings();
    }).wait(350);
    s.pointerAt({ x: 520, y: 330 }).move(`nav-${COMMUNITY}`).click(`nav-${COMMUNITY}`);
    s.set((st) => {
      if (st.settings) Object.assign(st.settings, { nav: COMMUNITY, page: "community" });
    }).wait(500);
    s.move("browse").click("browse");
    s.set((st) => {
      if (st.settings) st.settings.page = "browse";
    }).wait(300);
    s.typeTo(
      (st) => st.settings?.query ?? "",
      (st, v) => {
        if (st.settings) st.settings.query = v;
      },
      "BRAT",
    ).wait(400);
    s.move("brat-card").click("brat-card");
    s.set((st) => {
      if (st.settings) st.settings.picked = true;
    }).wait(500);
    s.move("install").click("install");
    s.set((st) => {
      if (st.settings) st.settings.button = "Installing...";
    }).wait(800);
    s.set((st) => {
      if (st.settings) st.settings.button = "Enable";
    }).wait(450);
    s.click("install");
    s.set((st) => {
      if (st.settings) Object.assign(st.settings, { button: "Disable", installed: "BRAT" });
    }).wait(700);
    s.hidePointer().key("esc").wait(120);
    s.set((st) => {
      st.settings = null;
    }).wait(400);

    s.palette("beta plugin", "Add a beta plugin for testing", "BRAT: ");
    s.modal(
      (st) => `<div class="mtitle">Add beta plugin</div>
        <div style="font-size:12px;color:#666;margin-bottom:6px">GitHub repository for beta plugin</div>
        <div class="field focus">${st.repo ? escapeHtml(st.repo) : '<span class="ph">user/repository</span>'}<span class="caret"></span></div>
        <div class="mrow"><span class="btn">Cancel</span><span class="btn cta" data-id="add">Add plugin</span></div>`,
    ).wait(300);
    s.typeTo(
      (st) => st.repo,
      (st, v) => {
        st.repo = v;
      },
      "jekozyra/spsync",
    ).wait(400);
    s.pointerAt("add").wait(200).click("add").closeModal();
    s.hidePointer().wait(500);

    // The plugin shows this notice while it downloads the standalone CLI (installStandaloneCli in main.ts).
    s.notice("Downloading the spsync CLI 0.1.0...", { sticky: true, id: "download" }).wait(2400);
    s.hideNotice("download").wait(700);
    s.key("⌘ ,").wait(120);
    s.set((st) => {
      st.settings = { ...blankSettings(), nav: COMMUNITY, page: "community", installed: "BRAT, SharePoint Sync" };
    });
  },
});
