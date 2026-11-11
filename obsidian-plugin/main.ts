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
  Setting,
  SuggestModal,
  TFile,
} from "obsidian";

interface Settings {
  cliPath: string;
  autoSync: boolean;
  pullIntervalMinutes: number;
  pushIdleSeconds: number;
  suggestByDefault: boolean;
  folder: string;
}

const DEFAULTS: Settings = {
  cliPath: "~/.local/bin/spsync",
  autoSync: true,
  pullIntervalMinutes: 5,
  pushIdleSeconds: 30,
  suggestByDefault: false,
  folder: "SharePoint",
};

interface Hit {
  ref: string;
  name: string;
  webUrl: string;
  modified: string;
  by: string;
}

export default class SpsyncPlugin extends Plugin {
  settings: Settings = DEFAULTS;
  status!: HTMLElement;
  timers = new Map<string, number>();
  running = new Set<string>();

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.status = this.addStatusBarItem();
    this.setStatus("idle");

    this.addRibbonIcon("refresh-cw", "Sync with SharePoint", () => this.syncActive());

    this.addCommand({ id: "search", name: "Find and open a SharePoint document", callback: () => new QueryModal(this.app, this).open() });
    this.addCommand({ id: "recent", name: "Open a recent SharePoint document", callback: () => this.pickRecent() });
    this.addCommand({ id: "pull-link", name: "Open a SharePoint link", callback: () => new LinkModal(this.app, this).open() });
    this.addCommand({ id: "sync", name: "Sync this note", checkCallback: (c) => this.linked(c, () => this.syncActive()) });
    this.addCommand({ id: "push-suggest", name: "Send edits as tracked changes", checkCallback: (c) => this.linked(c, () => this.syncActive(true)) });
    this.addCommand({ id: "sync-all", name: "Sync all linked notes", callback: () => this.syncAll(true) });
    this.addCommand({ id: "open-web", name: "Open this document in SharePoint", checkCallback: (c) => this.linked(c, () => this.openWeb()) });
    this.addCommand({ id: "create", name: "Create a Word document from this note", callback: () => this.createFromActive() });
    this.addCommand({ id: "comment", name: "Comment on this paragraph", editorCallback: (e) => this.insertComment(e) });
    this.addCommand({ id: "reply", name: "Reply to this comment", editorCallback: (e) => this.insertReply(e) });

    this.addSettingTab(new SpsyncSettings(this.app, this));

    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (!this.settings.autoSync || !(file instanceof TFile) || !this.isLinked(file)) return;
        const prev = this.timers.get(file.path);
        if (prev) window.clearTimeout(prev);
        this.timers.set(
          file.path,
          window.setTimeout(() => {
            this.timers.delete(file.path);
            this.syncFile(file, this.settings.suggestByDefault, false);
          }, this.settings.pushIdleSeconds * 1000),
        );
      }),
    );
    this.registerInterval(
      window.setInterval(() => {
        if (this.settings.autoSync) this.syncAll(false);
      }, Math.max(1, this.settings.pullIntervalMinutes) * 60 * 1000),
    );
  }

  onunload() {
    for (const t of this.timers.values()) window.clearTimeout(t);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  // ---- helpers ----
  vaultPath(): string {
    const a = this.app.vault.adapter;
    if (a instanceof FileSystemAdapter) return a.getBasePath();
    throw new Error("SharePoint Sync needs the desktop app.");
  }

  cli(): string {
    const p = this.settings.cliPath.trim();
    return p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : p;
  }

  run(args: string[]): Promise<string> {
    return new Promise((resolve, reject) => {
      execFile(
        this.cli(),
        args,
        { cwd: this.vaultPath(), env: { ...process.env, SPSYNC_VAULT: this.vaultPath() }, maxBuffer: 20 * 1024 * 1024, timeout: 5 * 60 * 1000 },
        (err, stdout, stderr) => {
          if (err && (err as NodeJS.ErrnoException).code === "ENOENT") {
            reject(new Error(`spsync CLI not found at ${this.cli()}. Set its path in settings.`));
          } else if (err && !(err.code === 2)) {
            reject(new Error((stderr || stdout || err.message).trim()));
          } else {
            resolve((stdout || "").trim());
          }
        },
      );
    });
  }

  setStatus(text: string) {
    this.status.setText(`SharePoint: ${text}`);
  }

  isLinked(file: TFile): boolean {
    return !!this.app.metadataCache.getFileCache(file)?.frontmatter?.spsync;
  }

  linked(checking: boolean, fn: () => void): boolean {
    const f = this.app.workspace.getActiveFile();
    if (!f || !this.isLinked(f)) return false;
    if (!checking) fn();
    return true;
  }

  abs(file: TFile): string {
    return path.join(this.vaultPath(), file.path);
  }

  // ---- actions ----
  async syncFile(file: TFile, suggest: boolean, loud: boolean) {
    if (this.running.has(file.path)) return;
    this.running.add(file.path);
    this.setStatus(`syncing ${file.basename}...`);
    try {
      const args = ["sync", this.abs(file)];
      if (suggest) args.push("--suggest");
      const out = await this.run(args);
      const quiet = /: unchanged\./.test(out);
      if (loud || !quiet) new Notice(out, out.includes("conflict") ? 0 : 6000);
      this.setStatus(out.includes("conflict") ? `conflict in ${file.basename}` : `synced ${new Date().toLocaleTimeString()}`);
    } catch (e) {
      new Notice(`SharePoint sync failed: ${(e as Error).message}`, 10000);
      this.setStatus("error");
    } finally {
      this.running.delete(file.path);
    }
  }

  async syncActive(suggest = this.settings.suggestByDefault) {
    const f = this.app.workspace.getActiveFile();
    if (!f || !this.isLinked(f)) {
      new Notice("This note is not linked to SharePoint.");
      return;
    }
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    if (view) await view.save();
    await this.syncFile(f, suggest, true);
  }

  async syncAll(loud: boolean) {
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (this.isLinked(f) && !this.timers.has(f.path)) await this.syncFile(f, this.settings.suggestByDefault, loud);
    }
  }

  async pull(ref: string) {
    this.setStatus("downloading...");
    try {
      const out = await this.run(["pull", ref, "--vault", this.vaultPath()]);
      const m = out.match(/Pulled to (.+)$/m);
      if (m) {
        const rel = path.relative(this.vaultPath(), m[1].trim());
        await new Promise((r) => window.setTimeout(r, 300));
        const file = this.app.vault.getAbstractFileByPath(rel);
        if (file instanceof TFile) await this.app.workspace.getLeaf(false).openFile(file);
      }
      this.setStatus("idle");
    } catch (e) {
      new Notice(`Could not open document: ${(e as Error).message}`, 10000);
      this.setStatus("error");
    }
  }

  async search(query: string) {
    try {
      const hits = JSON.parse(await this.run(["search", query, "--json"])) as Hit[];
      if (!hits.length) return new Notice("No Word documents found.");
      new HitModal(this.app, this, hits).open();
    } catch (e) {
      new Notice(`Search failed: ${(e as Error).message}`, 10000);
    }
  }

  async pickRecent() {
    try {
      const hits = JSON.parse(await this.run(["recent", "--json"])) as Hit[];
      new HitModal(this.app, this, hits).open();
    } catch (e) {
      new Notice(`Could not list recent documents: ${(e as Error).message}`, 10000);
    }
  }

  openWeb() {
    const f = this.app.workspace.getActiveFile();
    const url = f && this.app.metadataCache.getFileCache(f)?.frontmatter?.sharepoint;
    if (url) window.open(url);
  }

  async createFromActive() {
    const f = this.app.workspace.getActiveFile();
    if (!f) return;
    if (this.isLinked(f)) return new Notice("This note is already linked to SharePoint.");
    new TextModal(this.app, "Synced folder path (or 'me' for your OneDrive root)", async (folder) => {
      try {
        const out = await this.run(["new", this.abs(f), "--folder", folder]);
        new Notice(out, 8000);
      } catch (e) {
        new Notice(`Could not create document: ${(e as Error).message}`, 10000);
      }
    }).open();
  }

  insertComment(editor: Editor) {
    let line = editor.getCursor().line;
    const last = editor.lastLine();
    while (line < last && editor.getLine(line + 1).trim() !== "") line++;
    // Skip past existing comment callouts attached to this block.
    let next = line + 1;
    while (next <= last) {
      const l = editor.getLine(next);
      if (l.trim() === "" && next + 1 <= last && /^>\s*\[!(comment|reply)\]/i.test(editor.getLine(next + 1))) {
        next += 1;
        while (next <= last && editor.getLine(next).startsWith(">")) next++;
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
    while (line > 0 && !/^>\s*\[!(comment|reply)\]/i.test(editor.getLine(line)) && editor.getLine(line).startsWith(">")) line--;
    const header = editor.getLine(line);
    const m = header.match(/id:(\d+)/);
    if (!/^>\s*\[!(comment|reply)\]/i.test(header) || !m) {
      new Notice("Put the cursor inside an existing comment to reply.");
      return;
    }
    const parent = header.match(/re:(\d+)/)?.[1] ?? m[1];
    let end = line;
    while (end + 1 <= editor.lastLine() && editor.getLine(end + 1).startsWith(">")) end++;
    const text = `\n\n> [!reply] re:${parent}\n> `;
    editor.replaceRange(text, { line: end, ch: editor.getLine(end).length });
    editor.setCursor({ line: end + 3, ch: 2 });
  }
}

class TextModal extends Modal {
  constructor(app: App, private prompt: string, private onSubmit: (v: string) => void) {
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

class HitModal extends SuggestModal<Hit> {
  constructor(app: App, private plugin: SpsyncPlugin, private hits: Hit[]) {
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
  constructor(app: App, private plugin: SpsyncPlugin) {
    super(app, plugin);
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    const s = this.plugin.settings;
    const save = () => this.plugin.saveSettings();
    new Setting(containerEl).setName("spsync CLI path").setDesc("Run `spsync login` once in a terminal before using the plugin.").addText((t) =>
      t.setValue(s.cliPath).onChange(async (v) => {
        s.cliPath = v;
        await save();
      }),
    );
    new Setting(containerEl).setName("Sync automatically").setDesc("Push edits after you stop typing, and pull SharePoint changes on a timer.").addToggle((t) =>
      t.setValue(s.autoSync).onChange(async (v) => {
        s.autoSync = v;
        await save();
      }),
    );
    new Setting(containerEl).setName("Push after idle (seconds)").addText((t) =>
      t.setValue(String(s.pushIdleSeconds)).onChange(async (v) => {
        s.pushIdleSeconds = Math.max(5, Number(v) || DEFAULTS.pushIdleSeconds);
        await save();
      }),
    );
    new Setting(containerEl).setName("Check SharePoint every (minutes)").setDesc("Takes effect after reload.").addText((t) =>
      t.setValue(String(s.pullIntervalMinutes)).onChange(async (v) => {
        s.pullIntervalMinutes = Math.max(1, Number(v) || DEFAULTS.pullIntervalMinutes);
        await save();
      }),
    );
    new Setting(containerEl).setName("Send edits as tracked changes").setDesc("Recommended for other people's documents. Owners accept or reject them in Word.").addToggle((t) =>
      t.setValue(s.suggestByDefault).onChange(async (v) => {
        s.suggestByDefault = v;
        await save();
      }),
    );
  }
}
