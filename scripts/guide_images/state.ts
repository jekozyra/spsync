/**
 * The state of one animation frame, and the sample content that the scenes share.
 *
 * A frame is a pure function of time. The scene runner builds a fresh State for each frame, replays
 * the script actions onto it, and renders it to HTML. Nothing in a State outlives its frame.
 *
 * The sample content comes from `scripts/word_fixtures.py`. The guide images must not show real
 * names, employer names, or work content.
 */

export const APP_NAMES = ["obsidian", "word", "browser", "finder", "sys"] as const;
export type AppName = (typeof APP_NAMES)[number];

export interface Point {
  x: number;
  y: number;
}

/** A pointer target: the `data-id` of an element in the frame, or a point on the stage. */
export type Target = string | Point;

export interface Caret {
  line: number;
  ch: number;
}

export interface LineRange {
  from: number;
  to: number;
}

/** The Markdown source of the open note. The block with the caret or a selection shows its source. */
export interface Note {
  lines: string[];
  cur: Caret | null;
  sel: LineRange | null;
}

export interface FileEntry {
  name: string;
  dir?: boolean;
  nested?: boolean;
}

/** The opacity, scale, and blur in pixels of an app window or an overlay. */
export interface Layer {
  o: number;
  s: number;
  blur: number;
}

export interface Notice {
  id: string;
  text: string;
  o: number;
  y: number;
}

export interface KeyChip {
  label: string;
  o: number;
  y: number;
}

export interface Hit {
  name: string;
  meta: string;
}

/** The command palette, or the document picker that `HitModal` in the plugin shows. */
export type Prompt =
  | { kind: "command"; query: string; placeholder: string; pick?: string }
  | { kind: "hits"; query: string; placeholder: string; hits: Hit[]; pick?: string };

export interface Modal {
  o: number;
  s: number;
  style: string;
  render: () => string;
}

export interface Pointer {
  from: Target | null;
  to: Target | null;
  p: number;
  o: number;
}

export interface Press {
  id: string;
  amount: number;
}

export interface WordParagraph {
  kind: "h1" | "h2" | "li" | "p";
  html: string;
  changeBar?: boolean;
}

export interface WordWindow {
  trackChanges: boolean;
  paragraphs: WordParagraph[];
}

export interface LibraryRow {
  name: string;
  modified: string;
  by: string;
}

/** A SharePoint document library in the browser. `toast` is the opacity of the confirmation. */
export interface LibraryWindow {
  rows: LibraryRow[];
  hover: string | null;
  toast: number;
  toastText: string;
}

export interface FinderRow {
  name: string;
  kind: string;
  dir?: boolean;
}

export interface FinderSidebarItem {
  heading?: string;
  name?: string;
  cloud?: boolean;
  selected?: boolean;
}

export interface FinderWindow {
  title: string;
  sidebar: FinderSidebarItem[];
  rows: FinderRow[];
  selected: number;
  path: string[];
}

/** System Settings > Privacy & Security > Automation. `toggle` runs from 0 (off) to 1 (on). */
export interface AutomationWindow {
  toggle: number;
}

export interface State {
  layers: Partial<Record<AppName, Layer>>;
  order: AppName[];
  files: readonly FileEntry[];
  active: string | null;
  note: Note | null;
  props: readonly (readonly [string, string])[] | null;
  scroll: number;
  status: string;
  prompt: Prompt | null;
  modal: Modal | null;
  notices: Notice[];
  key: KeyChip | null;
  pointer: Pointer;
  press: Press | null;
  word: WordWindow | null;
  library: LibraryWindow | null;
  finder: FinderWindow | null;
  automation: AutomationWindow | null;
}

export function baseState(): State {
  return {
    layers: { obsidian: { o: 1, s: 1, blur: 0 } },
    order: ["obsidian"],
    files: [],
    active: null,
    note: null,
    props: null,
    scroll: 0,
    status: "SharePoint: idle",
    prompt: null,
    modal: null,
    notices: [],
    key: null,
    pointer: { from: null, to: null, p: 1, o: 0 },
    press: null,
    word: null,
    library: null,
    finder: null,
    automation: null,
  };
}

/** The sample document from `scripts/word_fixtures.py`, as `spsync pull` writes it. */
export function sampleNoteLines(): string[] {
  return [
    "# Project plan",
    "",
    "This is **important** and *subtle* text.",
    "",
    "- First bullet",
    "- Second bullet",
    "",
    "## Details",
    "",
    "Commented paragraph here.",
    "",
    "> [!comment] Alice Smith · 2026-05-12 · id:0",
    "> Please expand.",
    "",
    "| A | B |",
    "| --- | --- |",
    "| 1 | 2 |",
    "",
    "Closing line.",
  ];
}

// The frontmatter keys `spsync` and `sharepoint` are the ones that `spsync pull` writes.
const SAMPLE_PROPS = [
  ["spsync", "b!SampleDrive:01SAMPLEITEM"],
  ["sharepoint", "https://sample.sharepoint.com/sites/SampleTeam/Shared Documents/Project plan.docx"],
] as const;

export const FILES: readonly FileEntry[] = [
  { name: "Daily", dir: true },
  { name: "Inbox.md" },
  { name: "SharePoint", dir: true },
];
export const SAMPLE_NOTE_NAME = "Project plan.md";
const FILES_LINKED: readonly FileEntry[] = [...FILES, { name: SAMPLE_NOTE_NAME, nested: true }];

/** The status bar text after a sync. The time is fixed, so every frame of every scene matches. */
export const SYNCED_STATUS = "SharePoint: synced 10:42:16 AM";

/** Open the sample note, linked to SharePoint, as at the end of step 3 of the guide. */
export function withLinkedNote<S extends State>(st: S, { props = true }: { props?: boolean } = {}): S {
  st.files = FILES_LINKED;
  st.active = SAMPLE_NOTE_NAME;
  st.note = { lines: sampleNoteLines(), cur: null, sel: null };
  st.props = props ? SAMPLE_PROPS : null;

  return st;
}
