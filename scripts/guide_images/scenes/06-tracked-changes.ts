/* Step 6: send an edit as a tracked change, then see the tracked change in Word. */
import { scene } from "../scene.ts";
import { withLinkedNote, type State, type WordParagraph } from "../state.ts";

// The sample document in Word, with the edit from this scene as a tracked change.
const TABLE_CELL = "display:inline-block;border:1px solid #bbb;padding:2px 30px";
const WORD_PARAGRAPHS: WordParagraph[] = [
  { kind: "h1", html: "Project plan" },
  { kind: "p", changeBar: true, html: "This is <b>important</b> and <i><del>subtle</del><ins>clear</ins></i> text." },
  { kind: "li", html: "First bullet" },
  { kind: "li", html: "Second bullet" },
  { kind: "h2", html: "Details" },
  { kind: "p", html: '<span class="wcm">Commented paragraph here.</span>' },
  {
    kind: "p",
    html: `<span style="${TABLE_CELL}">A</span><span style="${TABLE_CELL};border-left:0">B</span><br><span style="${TABLE_CELL};border-top:0">1</span><span style="${TABLE_CELL};border-left:0;border-top:0">2</span>`,
  },
  { kind: "p", html: "Closing line." },
];

const EDITED_WORD = "subtle";

scene<State>({
  holdEndMs: 2400,
  geometry: { word: "inset:30px 40px 20px 60px" },
  init: (st) => ({ ...withLinkedNote(st), word: { trackChanges: false, paragraphs: WORD_PARAGRAPHS } }),
  script: (s) => {
    s.wait(600).caret(2, `This is **important** and *${EDITED_WORD}`.length).wait(400);
    s.backspace(EDITED_WORD.length).wait(150).typeNote("clear").wait(500);
    s.noCaret().wait(400);
    s.sync("Project plan.md: pushed. 1 edited, 0 added, 0 removed, 0 comments, 0 replies", {
      command: "Send edits as tracked changes",
      query: "tracked",
    });
    s.wait(2400);
    s.switchTo("word");
  },
});
