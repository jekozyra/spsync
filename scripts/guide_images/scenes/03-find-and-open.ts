/* Step 3: find a document from the command palette, and open it as a note. */
import { escapeHtml } from "../motion.ts";
import { scene } from "../scene.ts";
import { FILES, withLinkedNote, type Hit, type State } from "../state.ts";

// `renderSuggestion` in HitModal shows the name, then the modified date and the author.
const HITS: Hit[] = [
  { name: "Project plan.docx", meta: "2026-05-12 Alice Smith" },
  { name: "Project plan (archive).docx", meta: "2026-02-03 Sam Lee" },
];

type FindState = State & { query: string };

scene<FindState>({
  holdEndMs: 2200,
  init: (st) => ({ ...st, files: FILES, query: "" }),
  script: (s) => {
    s.wait(500).palette("find open", "Find and open a SharePoint document");
    s.modal(
      (st) =>
        `<div class="mtitle">Search SharePoint for a Word document</div><div class="field focus">${escapeHtml(st.query)}<span class="caret"></span></div>`,
    ).wait(300);
    s.typeTo(
      (st) => st.query,
      (st, v) => {
        st.query = v;
      },
      "project plan",
    ).wait(400);
    s.key("↩").wait(120).closeModal().wait(500);
    s.set((st) => {
      st.prompt = { kind: "hits", query: "", placeholder: "Pick a document to open as a note", hits: HITS, pick: HITS[0].name };
    }).wait(1300);
    s.key("↩").wait(120);
    s.set((st) => {
      st.prompt = null;
    });
    s.status("SharePoint: downloading...").wait(1000);
    s.set((st) => {
      withLinkedNote(st);
    });
    s.status("SharePoint: idle");
  },
});
