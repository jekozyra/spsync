import { execFile } from "child_process";
import * as os from "os";
import * as path from "path";
import {
  App,
  Editor,
  FileSystemAdapter,
  MarkdownView,
  Modal,
  Notice,
  Plugin,
  PluginSettingTab,
  requestUrl,
  Setting,
  SuggestModal,
  TFile,
} from "obsidian";

import { SHARED_INSTALL_ROOT, standaloneCli } from "./standalone-cli.ts";

interface Settings {
  cliPath: string;
  autoSync: boolean;
  pullIntervalMinutes: number;
  pushIdleSeconds: number;
  suggestByDefault: boolean;
  folder: string;
}

const DEFAULTS: Settings = {
  // An empty path runs the standalone build that the plugin downloads.
  cliPath: "",
  autoSync: true,
  pullIntervalMinutes: 5,
  pushIdleSeconds: 30,
  suggestByDefault: false,
  folder: "SharePoint",
};

/** One search result, as printed by `spsync search --json` and `spsync recent --json`. */
interface Hit {
  ref: string;
  name: string;
  webUrl: string;
  modified: string;
  by: string;
}

/** One setup check, as printed by `spsync doctor --json` (`Check` in doctor.py). */
interface SetupCheck {
  name: string;
  ok: boolean;
  required: boolean;
  detail: string;
  fix: string;
}

/** The output of `spsync doctor --json`. `complete` is true when every required check passed. */
interface SetupReport {
  complete: boolean;
  checks: SetupCheck[];
}

/** The settings that `spsync mode --json` prints. */
interface ModeReport {
  backend: string;
  author: string;
  roots: string[];
}

// Frontmatter keys that `spsync pull` writes.
const FM_REF = "spsync";
const FM_URL = "sharepoint";
const WORD_REF_PREFIX = "word:";

// `spsync sync` exits with this code when a note has conflicts; the output still describes the result.
const EXIT_CONFLICT = 2;

// `spsync doctor` exits with this code when a required check fails; the output still lists every check.
const EXIT_SETUP_INCOMPLETE = 3;
const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60 * MS_PER_SECOND;
const CLI_TIMEOUT_MS = 5 * MS_PER_MINUTE;
const CLI_MAX_OUTPUT_BYTES = 20 * 1024 * 1024;

// Obsidian indexes a new note shortly after the CLI writes it.
const INDEX_WAIT_MS = 300;
const STICKY_NOTICE = 0;
const RESULT_NOTICE_MS = 6000;
const CREATED_NOTICE_MS = 8000;
const ERROR_NOTICE_MS = 10000;
const MIN_PUSH_IDLE_SECONDS = 5;
const MIN_PULL_INTERVAL_MINUTES = 1;
const CALLOUT_HEADER = /^>\s*\[!(comment|reply)\]/i;

function notify(message: string, durationMs?: number): Notice {
  return new Notice(message, durationMs);
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export default class SpsyncPlugin extends Plugin {
  settings: Settings = DEFAULTS;
  status!: HTMLElement;
  timers = new Map<string, number>();
  running = new Set<string>();
  // The install that is in progress. Commands that start during the install wait for the same install.
  cliInstall: Promise<string> | null = null;

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.status = this.addStatusBarItem();
    this.setStatus("idle");

    this.addRibbonIcon("refresh-cw", "Sync with SharePoint", () => this.syncActive());

    this.addCommand({
      id: "search",
      name: "Find and open a SharePoint document",
      callback: () => new QueryModal(this.app, this).open(),
    });
    this.addCommand({
      id: "recent",
      name: "Open a recent SharePoint document",
      callback: () => this.pickRecent(),
    });
    this.addCommand({
      id: "pull-link",
      name: "Open a SharePoint link",
      callback: () => new LinkModal(this.app, this).open(),
    });
    this.addCommand({
      id: "sync",
      name: "Sync this note",
      checkCallback: (c) => this.linked(c, () => this.syncActive()),
    });
    this.addCommand({
      id: "push-suggest",
      name: "Send edits as tracked changes",
      checkCallback: (c) => this.linked(c, () => this.syncActive(true)),
    });
    this.addCommand({
      id: "sync-all",
      name: "Sync all linked notes",
      callback: () => this.syncAll(true),
    });
    this.addCommand({
      id: "open-web",
      name: "Open this document in SharePoint",
      checkCallback: (c) => this.linked(c, () => this.openWeb()),
    });
    this.addCommand({
      id: "create",
      name: "Create a Word document from this note",
      callback: () => this.createFromActive(),
    });
    this.addCommand({
      id: "check-setup",
      name: "Check setup",
      callback: () => this.checkSetup(),
    });
    this.addCommand({
      id: "comment",
      name: "Comment on this paragraph",
      editorCallback: (e) => this.insertComment(e),
    });
    this.addCommand({
      id: "reply",
      name: "Reply to this comment",
      editorCallback: (e) => this.insertReply(e),
    });

    this.addSettingTab(new SpsyncSettings(this.app, this));

    // Install the CLI for a new plugin version at startup, so the first command does not wait for the download.
    this.app.workspace.onLayoutReady(() => {
      this.cli().catch((e) =>
        notify(`Could not install the spsync CLI: ${errorText(e)}`, ERROR_NOTICE_MS),
      );
    });

    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (!this.settings.autoSync || !(file instanceof TFile) || !this.isLinked(file)) {
          return;
        }

        const prev = this.timers.get(file.path);

        if (prev) {
          window.clearTimeout(prev);
        }

        this.timers.set(
          file.path,
          window.setTimeout(() => {
            this.timers.delete(file.path);
            this.syncFile(file, this.settings.suggestByDefault, false);
          }, this.settings.pushIdleSeconds * MS_PER_SECOND),
        );
      }),
    );
    this.registerInterval(
      window.setInterval(
        () => {
          if (this.settings.autoSync) {
            this.syncAll(false);
          }
        },
        Math.max(MIN_PULL_INTERVAL_MINUTES, this.settings.pullIntervalMinutes) * MS_PER_MINUTE,
      ),
    );
  }

  onunload() {
    for (const t of this.timers.values()) {
      window.clearTimeout(t);
    }
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  // ---- helpers ----
  vaultPath(): string {
    const a = this.app.vault.adapter;

    if (a instanceof FileSystemAdapter) {
      return a.getBasePath();
    }

    throw new Error("SharePoint Sync needs the desktop app.");
  }

  async installStandaloneCli(): Promise<string> {
    const progress: Notice[] = [];

    try {
      return await standaloneCli({
        version: this.manifest.version,
        platform: process.platform,
        arch: process.arch,
        root: SHARED_INSTALL_ROOT,
        fetchBytes: async (url) => (await requestUrl({ url })).arrayBuffer,
        onDownloadStart: () => {
          progress.push(
            notify(`Downloading the spsync CLI ${this.manifest.version}...`, STICKY_NOTICE),
          );
        },
      });
    } finally {
      for (const notice of progress) {
        notice.hide();
      }
    }
  }

  /** The CLI to run: the `cliPath` setting, or the standalone build for this plugin version when it is empty. */
  async cli(): Promise<string> {
    const p = this.settings.cliPath.trim();

    if (p) {
      return p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : p;
    }

    this.cliInstall ??= this.installStandaloneCli().finally(() => {
      this.cliInstall = null;
    });

    return this.cliInstall;
  }

  /** Run the CLI. An exit code in `acceptedExitCodes` still describes a result, so it resolves with stdout. */
  async run(
    args: string[],
    acceptedExitCodes: readonly number[] = [EXIT_CONFLICT],
  ): Promise<string> {
    const cli = await this.cli();

    return new Promise((resolve, reject) => {
      execFile(
        cli,
        args,
        {
          cwd: this.vaultPath(),
          env: { ...process.env, SPSYNC_VAULT: this.vaultPath() },
          maxBuffer: CLI_MAX_OUTPUT_BYTES,
          timeout: CLI_TIMEOUT_MS,
        },
        (err, stdout, stderr) => {
          if (err && err.code === "ENOENT") {
            reject(
              new Error(`spsync CLI not found at ${cli}. Check the spsync CLI path in settings.`),
            );
          } else if (err && !acceptedExitCodes.some((code) => code === err.code)) {
            reject(new Error((stderr || stdout || err.message).trim()));
          } else {
            resolve((stdout || "").trim());
          }
        },
      );
    });
  }

  async hits(args: string[]): Promise<Hit[]> {
    // SAFETY: `--json` output is a list of objects with exactly the Hit keys (`_print_hits` in cli.py).
    return JSON.parse(await this.run([...args, "--json"])) as Hit[];
  }

  async setupReport(): Promise<SetupReport> {
    const out = await this.run(["doctor", "--json"], [EXIT_SETUP_INCOMPLETE]);

    // SAFETY: `spsync doctor --json` prints `complete` and a list of SetupCheck objects (`cmd_doctor` in cli.py).
    return JSON.parse(out) as SetupReport;
  }

  async modeReport(args: string[] = []): Promise<ModeReport> {
    // SAFETY: `spsync mode --json` prints exactly the ModeReport keys (`cmd_mode` in cli.py).
    return JSON.parse(await this.run(["mode", ...args, "--json"])) as ModeReport;
  }

  setStatus(text: string) {
    this.status.setText(`SharePoint: ${text}`);
  }

  isLinked(file: TFile): boolean {
    return !!this.app.metadataCache.getFileCache(file)?.frontmatter?.[FM_REF];
  }

  linked(checking: boolean, fn: () => void): boolean {
    const f = this.app.workspace.getActiveFile();

    if (!f || !this.isLinked(f)) {
      return false;
    }

    if (!checking) {
      fn();
    }

    return true;
  }

  abs(file: TFile): string {
    return path.join(this.vaultPath(), file.path);
  }

  // ---- actions ----
  async syncFile(file: TFile, suggest: boolean, loud: boolean) {
    if (this.running.has(file.path)) {
      return;
    }

    this.running.add(file.path);
    this.setStatus(`syncing ${file.basename}...`);

    try {
      const args = ["sync", this.abs(file)];

      if (suggest) {
        args.push("--suggest");
      }

      const out = await this.run(args);
      const quiet = /: unchanged\./.test(out);

      if (loud || !quiet) {
        notify(out, out.includes("conflict") ? STICKY_NOTICE : RESULT_NOTICE_MS);
      }

      this.setStatus(
        out.includes("conflict")
          ? `conflict in ${file.basename}`
          : `synced ${new Date().toLocaleTimeString()}`,
      );
    } catch (e) {
      notify(`SharePoint sync failed: ${errorText(e)}`, ERROR_NOTICE_MS);
      this.setStatus("error");
    } finally {
      this.running.delete(file.path);
    }
  }

  async syncActive(suggest = this.settings.suggestByDefault) {
    const f = this.app.workspace.getActiveFile();

    if (!f || !this.isLinked(f)) {
      notify("This note is not linked to SharePoint.");

      return;
    }

    const view = this.app.workspace.getActiveViewOfType(MarkdownView);

    if (view) {
      await view.save();
    }

    await this.syncFile(f, suggest, true);
  }

  isWord(file: TFile): boolean {
    return String(
      this.app.metadataCache.getFileCache(file)?.frontmatter?.[FM_REF] ?? "",
    ).startsWith(WORD_REF_PREFIX);
  }

  async syncAll(loud: boolean) {
    for (const f of this.app.vault.getMarkdownFiles()) {
      // Word-backed notes open Word to check for changes, so only sync them on request.
      if (!loud && this.isWord(f)) {
        continue;
      }

      if (this.isLinked(f) && !this.timers.has(f.path)) {
        // Each sync runs the CLI against the vault state; run them one at a time.
        // oxlint-disable-next-line no-await-in-loop
        await this.syncFile(f, this.settings.suggestByDefault, loud);
      }
    }
  }

  async pull(ref: string) {
    this.setStatus("downloading...");

    try {
      const out = await this.run(["pull", ref, "--vault", this.vaultPath()]);
      const m = out.match(/Pulled to (.+)$/m);

      if (m) {
        const rel = path.relative(this.vaultPath(), m[1].trim());
        await new Promise((r) => window.setTimeout(r, INDEX_WAIT_MS));
        const file = this.app.vault.getAbstractFileByPath(rel);

        if (file instanceof TFile) {
          await this.app.workspace.getLeaf(false).openFile(file);
        }
      }

      this.setStatus("idle");
    } catch (e) {
      notify(`Could not open document: ${errorText(e)}`, ERROR_NOTICE_MS);
      this.setStatus("error");
    }
  }

  async search(query: string) {
    try {
      const hits = await this.hits(["search", query]);

      if (!hits.length) {
        notify("No Word documents found.");

        return;
      }

      new HitModal(this.app, this, hits).open();
    } catch (e) {
      notify(`Search failed: ${errorText(e)}`, ERROR_NOTICE_MS);
    }
  }

  async pickRecent() {
    try {
      const hits = await this.hits(["recent"]);
      new HitModal(this.app, this, hits).open();
    } catch (e) {
      notify(`Could not list recent documents: ${errorText(e)}`, ERROR_NOTICE_MS);
    }
  }

  openWeb() {
    const f = this.app.workspace.getActiveFile();
    const url = f && this.app.metadataCache.getFileCache(f)?.frontmatter?.[FM_URL];

    if (url) {
      window.open(url);
    }
  }

  async createFromActive() {
    const f = this.app.workspace.getActiveFile();

    if (!f) {
      return;
    }

    if (this.isLinked(f)) {
      notify("This note is already linked to SharePoint.");

      return;
    }

    new TextModal(
      this.app,
      "Synced folder path (or 'me' for your OneDrive root)",
      async (folder) => {
        try {
          const out = await this.run(["new", this.abs(f), "--folder", folder]);
          notify(out, CREATED_NOTICE_MS);
        } catch (e) {
          notify(`Could not create document: ${errorText(e)}`, ERROR_NOTICE_MS);
        }
      },
    ).open();
  }

  async checkSetup() {
    const progress = notify("Checking setup. Word can start in the background.", STICKY_NOTICE);

    try {
      new SetupModal(this.app, await this.setupReport()).open();
    } catch (e) {
      notify(`Setup check failed: ${errorText(e)}`, ERROR_NOTICE_MS);
    } finally {
      progress.hide();
    }
  }

  insertComment(editor: Editor) {
    let line = editor.getCursor().line;
    const last = editor.lastLine();

    while (line < last && editor.getLine(line + 1).trim() !== "") {
      line += 1;
    }

    // Skip past existing comment callouts attached to this block.
    let next = line + 1;

    while (next <= last) {
      const l = editor.getLine(next);

      if (l.trim() === "" && next + 1 <= last && CALLOUT_HEADER.test(editor.getLine(next + 1))) {
        next += 1;

        while (next <= last && editor.getLine(next).startsWith(">")) {
          next += 1;
        }

        line = next - 1;
        continue;
      }

      break;
    }

    const end = editor.getLine(line).length;
    editor.replaceRange("\n\n> [!comment] ", { line, ch: end });
    editor.setCursor({ line: line + 2, ch: "> [!comment] ".length });
  }

  insertReply(editor: Editor) {
    let line = editor.getCursor().line;

    while (
      line > 0 &&
      !CALLOUT_HEADER.test(editor.getLine(line)) &&
      editor.getLine(line).startsWith(">")
    ) {
      line -= 1;
    }

    const header = editor.getLine(line);
    const m = header.match(/id:(\d+)/);

    if (!CALLOUT_HEADER.test(header) || !m) {
      notify("Put the cursor inside an existing comment to reply.");

      return;
    }

    const parent = header.match(/re:(\d+)/)?.[1] ?? m[1];
    let end = line;

    while (end + 1 <= editor.lastLine() && editor.getLine(end + 1).startsWith(">")) {
      end += 1;
    }

    const text = `\n\n> [!reply] re:${parent}\n> `;
    editor.replaceRange(text, { line: end, ch: editor.getLine(end).length });
    editor.setCursor({ line: end + 3, ch: 2 });
  }
}

class TextModal extends Modal {
  constructor(
    app: App,
    private prompt: string,
    private onSubmit: (v: string) => void,
  ) {
    super(app);
  }
  onOpen() {
    this.titleEl.setText(this.prompt);
    const input = this.contentEl.createEl("input", { type: "text" });
    input.style.width = "100%";
    input.focus();
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && input.value.trim()) {
        this.close();
        this.onSubmit(input.value.trim());
      }
    });
  }
  onClose() {
    this.contentEl.empty();
  }
}

class QueryModal extends TextModal {
  constructor(app: App, plugin: SpsyncPlugin) {
    super(app, "Search SharePoint for a Word document", (q) => plugin.search(q));
  }
}

class LinkModal extends TextModal {
  constructor(app: App, plugin: SpsyncPlugin) {
    super(app, "Paste a SharePoint link or the path of a synced .docx", (url) => plugin.pull(url));
  }
}

function checkLabel(check: SetupCheck): string {
  if (check.ok) {
    return "Pass";
  }

  return check.required ? "Fail" : "Fail (optional)";
}

class SetupModal extends Modal {
  constructor(
    app: App,
    private report: SetupReport,
  ) {
    super(app);
  }
  onOpen() {
    this.titleEl.setText(this.report.complete ? "Setup is complete" : "Setup needs attention");

    for (const check of this.report.checks) {
      const row = this.contentEl.createDiv();
      row.createEl("strong", { text: `${checkLabel(check)}: ${check.name}` });
      row.createDiv({ text: check.detail });

      if (check.fix) {
        row.createDiv({ text: `Fix: ${check.fix}` });
      }
    }
  }
  onClose() {
    this.contentEl.empty();
  }
}

class HitModal extends SuggestModal<Hit> {
  constructor(
    app: App,
    private plugin: SpsyncPlugin,
    private hits: Hit[],
  ) {
    super(app);
    this.setPlaceholder("Pick a document to open as a note");
  }
  getSuggestions(q: string): Hit[] {
    const s = q.toLowerCase();

    return this.hits.filter((h) => h.name.toLowerCase().includes(s));
  }
  renderSuggestion(h: Hit, el: HTMLElement) {
    el.createEl("div", { text: h.name });
    el.createEl("small", { text: `${h.modified} ${h.by}`.trim() });
  }
  onChooseSuggestion(h: Hit) {
    this.plugin.pull(h.ref);
  }
}

class SpsyncSettings extends PluginSettingTab {
  constructor(
    app: App,
    private plugin: SpsyncPlugin,
  ) {
    super(app, plugin);
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    const s = this.plugin.settings;
    const save = () => this.plugin.saveSettings();
    const add = () => new Setting(containerEl);
    add()
      .setName("spsync CLI path")
      .setDesc(
        "Leave empty to run the spsync CLI that the plugin downloads for its version. Enter a path to run another build, such as ~/.local/bin/spsync.",
      )
      .addText((t) =>
        t.setValue(s.cliPath).onChange(async (v) => {
          s.cliPath = v;
          await save();
        }),
      );
    add()
      .setName("Author name")
      .setDesc(
        "The name on your comments and tracked changes. spsync saves it for the CLI too. Leave it empty to keep the current name.",
      )
      .addText((t) => {
        t.setPlaceholder("Loading...");
        this.plugin
          .modeReport()
          .then((mode) => t.setValue(mode.author))
          .catch(() => t.setPlaceholder("Could not run the spsync CLI"));
        // "change" fires when the field loses focus, so each keystroke does not run the CLI.
        t.inputEl.addEventListener("change", async () => {
          const author = t.getValue().trim();

          if (!author) {
            return;
          }

          try {
            await this.plugin.modeReport(["--author", author]);
            notify(`Author name set to ${author}.`);
          } catch (e) {
            notify(`Could not save the author name: ${errorText(e)}`, ERROR_NOTICE_MS);
          }
        });
      });
    add()
      .setName("Sync automatically")
      .setDesc("Push edits after you stop typing, and pull SharePoint changes on a timer.")
      .addToggle((t) =>
        t.setValue(s.autoSync).onChange(async (v) => {
          s.autoSync = v;
          await save();
        }),
      );
    add()
      .setName("Push after idle (seconds)")
      .addText((t) =>
        t.setValue(String(s.pushIdleSeconds)).onChange(async (v) => {
          s.pushIdleSeconds = Math.max(
            MIN_PUSH_IDLE_SECONDS,
            Number(v) || DEFAULTS.pushIdleSeconds,
          );
          await save();
        }),
      );
    add()
      .setName("Check SharePoint every (minutes)")
      .setDesc("Takes effect after reload.")
      .addText((t) =>
        t.setValue(String(s.pullIntervalMinutes)).onChange(async (v) => {
          s.pullIntervalMinutes = Math.max(
            MIN_PULL_INTERVAL_MINUTES,
            Number(v) || DEFAULTS.pullIntervalMinutes,
          );
          await save();
        }),
      );
    add()
      .setName("Send edits as tracked changes")
      .setDesc("Recommended for other people's documents. Owners accept or reject them in Word.")
      .addToggle((t) =>
        t.setValue(s.suggestByDefault).onChange(async (v) => {
          s.suggestByDefault = v;
          await save();
        }),
      );
  }
}
