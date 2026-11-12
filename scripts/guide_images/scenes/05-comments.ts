/* Step 5: add a comment, reply to a comment, and resolve a comment. */
import { scene } from "../scene.ts";
import { withLinkedNote, type State } from "../state.ts";

// The scroll offset that puts "Commented paragraph here." at the top of the editor.
const DETAILS_SCROLL_PX = 171;
const NEW_COMMENT = "> [!comment] ";

scene<State>({
  holdEndMs: 1800,
  init: (st) => withLinkedNote(st, { props: false }),
  script: (s) => {
    s.wait(400).scrollTo(DETAILS_SCROLL_PX).wait(200);

    // "Comment on this paragraph" (insertComment in main.ts) adds a comment callout under the paragraph.
    s.caret(18).wait(400);
    s.palette("comment on", "Comment on this paragraph");
    s.set((st) => {
      if (!st.note) return;

      st.note.lines.push("", NEW_COMMENT);
      st.note.cur = { line: 20, ch: NEW_COMMENT.length };
    }).wait(250);
    s.typeNote("Can we name a date for this?").wait(700);

    // "Reply to this comment" (insertReply in main.ts) adds a reply with the id of the comment.
    s.caret(12).wait(500);
    s.palette("reply", "Reply to this comment");
    s.set((st) => {
      if (!st.note) return;

      st.note.lines.splice(13, 0, "", "> [!reply] re:0", "> ");
      st.note.cur = { line: 15, ch: 2 };
    }).wait(250);
    s.typeNote("Done. I added the details below.").wait(700);

    // Resolve: add "· resolved" to the comment header.
    s.caret(11).wait(300);
    s.typeNote(" · resolved").wait(600);
    s.noCaret().wait(500);
    s.sync("Project plan.md: pushed. 0 edited, 0 added, 0 removed, 1 comments, 1 replies, 1 resolution changes");
    s.wait(3600);
  },
});
