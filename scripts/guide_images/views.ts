/**
 * Views: each app window renders a State to HTML. The views only read state.
 *
 * The Obsidian view shows the live preview of the note. The block that holds the caret or a
 * selection shows its Markdown source; every other block shows its rendered form, as in Obsidian.
 *
 * note.lines --group by blank lines--> blocks --caret inside?--> source lines with syntax tokens
 *                                                             `--> rendered heading, list, callout, table
 *
 * Text that the plugin or the CLI shows, such as command names, matches `obsidian-plugin/main.ts`
 * and `src/spsync/`. Change it here when it changes there.
 */
import { escapeHtml, lerp } from "./motion.ts";
import type { AppName, Modal, Note, Prompt, State } from "./state.ts";

export interface AppView {
  className: string;
  render: (st: State, overlay: string) => string;
}

// The command names that `addCommand` registers in obsidian-plugin/main.ts, plus BRAT and core commands.
const COMMANDS = [
  "SharePoint Sync: Find and open a SharePoint document",
  "SharePoint Sync: Open a recent SharePoint document",
  "SharePoint Sync: Open a SharePoint link",
  "SharePoint Sync: Sync this note",
  "SharePoint Sync: Send edits as tracked changes",
  "SharePoint Sync: Sync all linked notes",
  "SharePoint Sync: Open this document in SharePoint",
  "SharePoint Sync: Create a Word document from this note",
  "SharePoint Sync: Check setup",
  "SharePoint Sync: Comment on this paragraph",
  "SharePoint Sync: Reply to this comment",
  "BRAT: Add a beta plugin for testing",
  "BRAT: Check for updates to all beta plugins",
  "Daily notes: Open today's daily note",
  "Editor: Toggle bold",
  "Files: Create new note",
];
const MAX_SUGGESTIONS = 6;

const PENCIL_ICON =
  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#086ddd" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';

export const POINTER_SVG =
  '<svg id="pointer" width="20" height="24" viewBox="0 0 20 24"><path d="M2 2 L2 19 L6.5 15 L9.5 22 L12.5 20.8 L9.6 14 L15.5 14 Z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';

const TRAFFIC_LIGHTS = '<div class="lights"><i></i><i></i><i></i></div>';

// ---- Obsidian live preview ----

function inline(md: string): string {
  return escapeHtml(md)
    .replace(/%%(.+?)%%/g, '<span class="cmt">%%$1%%</span>')
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>")
    .replace(/==(.+?)==/g, "<mark>$1</mark>")
    .replace(/~~(.+?)~~/g, "<s>$1</s>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a class="lnk">$1</a>');
}

// Markdown syntax that the source view greys out, and the callout types that it shows in the accent color.
const SOURCE_TOKENS: readonly (readonly [RegExp, string])[] = [
  [/^#{1,6} /g, "tok"],
  [/^(> ?)+/g, "tok"],
  [/\[!(comment|reply|conflict)\]/gi, "ctok"],
  [/^- /g, "tok"],
  [/\*\*|==|~~|%%/g, "tok"],
  [/\|/g, "tok"],
];

function tokenClasses(text: string): string[] {
  const classes = new Array<string>(text.length).fill("");

  for (const [pattern, className] of SOURCE_TOKENS) {
    for (const match of text.matchAll(new RegExp(pattern.source, pattern.flags))) {
      for (let i = match.index; i < match.index + match[0].length; i++) {
        if (!classes[i]) classes[i] = className;
      }
    }
  }

  return classes;
}

function sourceLine(text: string, caretCh: number | null, selected: boolean): string {
  const classes = tokenClasses(text);
  let html = "";
  let open = "";

  for (let i = 0; i <= text.length; i++) {
    if (i === caretCh) {
      html += open ? `</span><span class="caret"></span><span class="${open}">` : '<span class="caret"></span>';
    }

    if (i === text.length) break;

    if (classes[i] !== open) {
      if (open) html += "</span>";
      if (classes[i]) html += `<span class="${classes[i]}">`;
      open = classes[i];
    }

    html += escapeHtml(text[i]);
  }

  if (open) html += "</span>";

  const heading = /^# /.test(text) ? " h1" : /^## /.test(text) ? " h2" : "";

  return `<div class="ln${heading}${selected ? " sel" : ""}">${html || "&#8203;"}</div>`;
}

function calloutHtml(type: string, title: string, bodyLines: string[]): string {
  const heading = title || type[0].toUpperCase() + type.slice(1);
  const body = bodyLines.map((l) => l.replace(/^> ?/, "")).filter((l, i, all) => l || i < all.length - 1);
  const bodyHtml = body.length ? `<div class="cb">${body.map((l) => (l ? inline(l) : "&nbsp;")).join("<br>")}</div>` : "";

  return `<div class="callout ${type.toLowerCase()}"><div class="ct">${PENCIL_ICON}<span>${inline(heading)}</span></div>${bodyHtml}</div>`;
}

function tableHtml(lines: string[]): string {
  const rows = lines.filter((l) => !/^\|\s*-/.test(l)).map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));
  const cells = (row: string[], tag: string) => row.map((c) => `<${tag}>${inline(c)}</${tag}>`).join("");

  return `<table class="md">${rows.map((row, i) => `<tr>${cells(row, i ? "td" : "th")}</tr>`).join("")}</table>`;
}

function renderedBlock(lines: string[]): string {
  const first = lines[0];
  const callout = first.match(/^> ?\[!(\w+)\] ?(.*)$/);

  if (/^# /.test(first)) return `<div class="h1">${inline(first.slice(2))}</div>`;
  if (/^## /.test(first)) return `<div class="h2">${inline(first.slice(3))}</div>`;
  if (/^- /.test(first)) return `<ul class="list">${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
  if (callout) return calloutHtml(callout[1], callout[2], lines.slice(1));
  if (/^\|/.test(first)) return tableHtml(lines);
  if (/^%%/.test(first)) return `<div class="ln cmt">${lines.map(escapeHtml).join("<br>")}</div>`;

  return `<div class="ln">${lines.map(inline).join("<br>")}</div>`;
}

function noteHtml(note: Note): string {
  const { lines, cur, sel } = note;
  let html = "";
  let start = 0;

  while (start < lines.length) {
    if (lines[start] === "") {
      html += cur?.line === start ? sourceLine("", cur.ch, false) : '<div class="gap"></div>';
      start++;
      continue;
    }

    let end = start;

    while (end + 1 < lines.length && lines[end + 1] !== "") end++;

    const hasCaret = cur !== null && cur.line >= start && cur.line <= end;
    const hasSelection = sel !== null && sel.to >= start && sel.from <= end;

    if (hasCaret || hasSelection) {
      for (let k = start; k <= end; k++) {
        const selected = sel !== null && k >= sel.from && k <= sel.to;
        html += sourceLine(lines[k], cur?.line === k ? cur.ch : null, selected);
      }
    } else {
      html += renderedBlock(lines.slice(start, end + 1));
    }

    start = end + 1;
  }

  return html;
}

function highlight(text: string, words: string[]): string {
  let html = escapeHtml(text);

  for (const word of words) {
    html = html.replace(new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "i"), "<b>$1</b>");
  }

  return html;
}

function suggestions(prompt: Prompt): string {
  if (prompt.kind === "command") {
    const words = prompt.query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = COMMANDS.filter((c) => words.every((w) => c.toLowerCase().includes(w))).slice(0, MAX_SUGGESTIONS);
    const selected = Math.max(0, prompt.pick ? matches.indexOf(prompt.pick) : 0);

    return matches
      .map((c, k) => {
        const [prefix, name] = c.split(": ");

        return `<div class="sugg${k === selected ? " on" : ""}"><span class="pfx">${highlight(`${prefix}: `, words)}</span>${highlight(name, words)}</div>`;
      })
      .join("");
  }

  const query = prompt.query.toLowerCase();
  const matches = prompt.hits.filter((h) => h.name.toLowerCase().includes(query));
  const selected = Math.max(0, prompt.pick ? matches.findIndex((h) => h.name === prompt.pick) : 0);

  return matches
    .map((h, k) => `<div class="sugg${k === selected ? " on" : ""}">${escapeHtml(h.name)}<small>${escapeHtml(h.meta)}</small></div>`)
    .join("");
}

function promptHtml(prompt: Prompt): string {
  const input = prompt.query
    ? `${escapeHtml(prompt.query)}<span class="caret"></span>`
    : `<span class="caret"></span><span class="ph">${escapeHtml(prompt.placeholder)}</span>`;
  const footer = '<div class="pfoot"><span>↑↓ to navigate</span><span>↵ to use</span><span>esc to dismiss</span></div>';

  return `<div class="dim"></div><div class="prompt"><div class="pin">${input}</div>${suggestions(prompt)}${footer}</div>`;
}

function modalHtml(modal: Modal): string {
  const style = `opacity:${modal.o};transform:translate(-50%,-50%) scale(${modal.s});${modal.style}`;

  return `<div class="dim" style="opacity:${modal.o}"></div><div class="modal" style="${style}">${modal.render()}</div>`;
}

function noticesHtml(st: State): string {
  const notices = st.notices.map((n) => `<div class="notice" style="opacity:${n.o};transform:translateY(${n.y}px)">${escapeHtml(n.text)}</div>`);

  return `<div class="notices">${notices.join("")}</div>`;
}

function obsidianView(st: State, overlay: string): string {
  const files = st.files
    .map((f) => `<div class="f${f.dir ? " dir" : ""}${f.nested ? " in" : ""}${f.name === st.active ? " on" : ""}">${escapeHtml(f.name)}</div>`)
    .join("");
  const tab = st.active ? st.active.replace(/\.md$/, "") : "New tab";
  let editor = '<div class="empty-editor">No file is open</div>';

  if (st.note) {
    const props = st.props
      ? `<div class="props">${st.props.map(([k, v]) => `<div><b>${escapeHtml(k)}</b><span>${escapeHtml(v)}</span></div>`).join("")}</div>`
      : "";
    editor = `<div class="doc" style="transform:translateY(${-st.scroll}px)">${props}${noteHtml(st.note)}</div>`;
  }

  return `
    <div class="titlebar">${TRAFFIC_LIGHTS}<div class="tabspace"></div><div class="tab">${escapeHtml(tab)}</div></div>
    <div class="body">
      <div class="ribbon"><i></i><i class="round"></i><i></i><i class="round"></i></div>
      <div class="files"><div class="vault">Notes</div>${files}</div>
      <div class="main"><div class="editor">${editor}</div><div class="status"><span>${escapeHtml(st.status)}</span></div></div>
      ${overlay}
      ${st.prompt ? promptHtml(st.prompt) : ""}
      ${st.modal ? modalHtml(st.modal) : ""}
      ${noticesHtml(st)}
    </div>`;
}

// ---- Word for Mac ----

const WORD_PARAGRAPH_CLASSES = { h1: "wh1", h2: "wh2", li: "wli", p: "" } as const;

function wordView(st: State): string {
  if (!st.word) return "";

  const paragraphs = st.word.paragraphs
    .map((p) => `<p class="${WORD_PARAGRAPH_CLASSES[p.kind]}${p.changeBar ? " bar" : ""}">${p.html}</p>`)
    .join("");
  const ribbon = ["New Comment", "Show Comments", "Track Changes", "All Markup ▾", "Accept ▾", "Reject ▾"]
    .map((b) => `<span class="rb${b === "Track Changes" && st.word?.trackChanges ? " on" : ""}">${b}</span>`)
    .join("");
  const tabs = ["Home", "Insert", "Draw", "Design", "Layout", "References", "Review", "View"]
    .map((t) => `<span${t === "Review" ? ' class="on"' : ""}>${t}</span>`)
    .join("");

  return `
    <div class="titlebar">${TRAFFIC_LIGHTS}<div class="wtitle" style="display:flex;gap:6px;justify-content:center;align-items:center"><span class="wicon">W</span>Project plan.docx</div></div>
    <div class="wtabs">${tabs}</div>
    <div class="wrib">${ribbon}</div>
    <div class="wcanvas"><div class="page">${paragraphs}</div></div>`;
}

// ---- SharePoint document library in the browser ----

function libraryView(st: State): string {
  const library = st.library;

  if (!library) return "";

  const rows = library.rows
    .map((r) => {
      const icon =
        r.kind === "folder" ? '<span class="folder"></span>' : '<span class="docx">W</span>';

      return `<div class="r"><div class="c1">${icon}${escapeHtml(r.name)}</div><div class="c2">${escapeHtml(r.modified)}</div><div class="c3">${escapeHtml(r.by)}</div></div>`;
    })
    .join("");
  const toast =
    library.toast > 0
      ? `<div class="sptoast" style="opacity:${library.toast};transform:translateY(${(1 - library.toast) * -8}px)">${escapeHtml(library.toastText)}</div>`
      : "";
  const button = (id: string, label: string) => `<span class="cb${library.hover === id ? " hl" : ""}" data-id="${id}">${label}</span>`;

  return `
    <div class="titlebar">${TRAFFIC_LIGHTS}<div class="btab"><span class="docx" style="background:#3b7d6e">S</span>Documents - Sample Team</div></div>
    <div class="addr"><span>‹ ›</span><div class="url">sample.sharepoint.com/sites/SampleTeam/Shared Documents</div></div>
    <div class="sitebar">
      <div class="site"><div class="logo">ST</div><div class="nm">Sample Team</div><span class="site-chevron">⌄</span><span class="site-link">↗</span><span class="site-link">◎</span></div>
      <div class="library-actions">${button("shortcut", "↗ Add shortcut to My files ▾")}<span class="more">•••</span><span class="separator"></span><span class="create">＋ Create or upload</span></div>
    </div>
    <div class="library-viewbar">
      <div class="library-views"><span class="library-view active">☷ All Documents</span><span class="library-view">☷ In channels</span><span class="library-view">＋ Add view</span></div>
      <div class="library-tools"><span class="filter">☰</span><span class="app word-app">W</span><span class="app sheet-app">X</span><span class="app slide-app">P</span><span class="details">☷ Details</span></div>
    </div>
    <div class="lst"><div class="r hd"><div class="c1">▯　Name　⌄</div><div class="c2">Modified　ⓘ　⌄</div><div class="c3">Modified By　⌄</div></div>${rows}</div>
    ${toast}`;
}

// ---- Finder ----

function finderView(st: State): string {
  const finder = st.finder;

  if (!finder) return "";

  const sidebar = finder.sidebar
    .map((s) => (s.heading ? `<div class="h">${escapeHtml(s.heading)}</div>` : `<div class="i${s.cloud ? " cloud" : ""}${s.selected ? " on" : ""}">${escapeHtml(s.name ?? "")}</div>`))
    .join("");
  const rows = finder.rows
    .map((r, k) => {
      const icon = r.dir ? '<span class="folder"></span>' : '<span class="docx">W</span>';

      return `<div class="r${k === finder.selected ? " on" : ""}" data-id="row-${k}"><div class="nm">${icon}${escapeHtml(r.name)}</div><div class="k">${escapeHtml(r.kind)}</div><div class="k cloudmark">☁</div></div>`;
    })
    .join("");

  return `
    <div class="titlebar">${TRAFFIC_LIGHTS}<div class="wtitle">${escapeHtml(finder.title)}</div></div>
    <div class="body2"><div class="fside">${sidebar}</div>
      <div class="fmain"><div class="r hd"><div class="nm">Name</div><div class="k">Kind</div><div class="k"></div></div>${rows}
        <div class="pathbar">${finder.path.map(escapeHtml).join("  ›  ")}</div></div></div>`;
}

// ---- System Settings ----

const SETTINGS_PANES = ["Wi-Fi", "Bluetooth", "Network", "General", "Appearance", "Desktop & Dock", "Privacy & Security", "Notifications"];
const SELECTED_PANE = "Privacy & Security";
// The track colors of a macOS switch: off is grey, on is green.
const TOGGLE_OFF_RGB = [213, 213, 216] as const;
const TOGGLE_ON_RGB = [52, 199, 89] as const;
const TOGGLE_TRAVEL_PX = 12;

function toggleHtml(on: number, id: string): string {
  const rgb = TOGGLE_OFF_RGB.map((off, i) => lerp(off, TOGGLE_ON_RGB[i], on)).join(",");

  return `<span class="tog" data-id="${id}" style="background:rgb(${rgb})"><i style="transform:translateX(${TOGGLE_TRAVEL_PX * on}px)"></i></span>`;
}

function automationView(st: State): string {
  if (!st.automation) return "";

  const sidebar = SETTINGS_PANES.map((n) => {
    const selected = n === SELECTED_PANE;

    return `<div class="i${selected ? " on" : ""}"><span class="ic"${selected ? ' style="background:#5b8def"' : ""}></span>${n}</div>`;
  }).join("");

  return `
    <div class="titlebar">${TRAFFIC_LIGHTS}<div class="wtitle">Automation</div></div>
    <div class="body2"><div class="sysside">${sidebar}</div>
      <div class="syspane"><h3>‹ Automation</h3>
        <div style="color:#666;font-size:11.5px;margin-bottom:12px">Allow the applications below to control other apps.</div>
        <div class="grp"><div class="gr">Obsidian</div><div class="gr sub">Microsoft Word${toggleHtml(st.automation.toggle, "word-toggle")}</div></div>
        <div class="grp"><div class="gr">Terminal</div><div class="gr sub">System Events${toggleHtml(1, "events-toggle")}</div></div>
      </div></div>`;
}

export const APP_VIEWS: Record<AppName, AppView> = {
  obsidian: { className: "obs", render: obsidianView },
  word: { className: "word", render: wordView },
  browser: { className: "browser", render: libraryView },
  finder: { className: "finder", render: finderView },
  sys: { className: "sys", render: automationView },
};
