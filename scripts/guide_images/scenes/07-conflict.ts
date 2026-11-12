/* Step 7: resolve a [!conflict] callout, then sync again. */
import { scene } from "../scene.ts";
import { withLinkedNote, type State } from "../state.ts";

// `conflict_callout` and the conflict result of `Session.sync` in src/spsync/core.py.
const CONFLICT_HEADER =
  "> [!conflict] SharePoint version of this section (changed while you were editing). Keep what you want, then delete this callout.";
const CONFLICT_RESULT =
  "Project plan.md: conflict. 1 conflicting section(s). Look for [!conflict] callouts in the note, fix them, delete the callouts, then sync again.";
const DETAILS_SCROLL_PX = 171;
const LOCAL_EDIT = "Closing line, with the new date";

scene<State>({
  holdEndMs: 1800,
  init: (st) => {
    const linked = withLinkedNote(st, { props: false });
    const lines = linked.note?.lines ?? [];
    lines[lines.length - 1] = `${LOCAL_EDIT}.`;
    lines.push("", CONFLICT_HEADER, "> Closing line, with the new budget.");

    return { ...linked, scroll: DETAILS_SCROLL_PX, status: "SharePoint: conflict in Project plan" };
  },
  script: (s) => {
    s.notice(CONFLICT_RESULT, { sticky: true, id: "conflict" }).wait(2400);
    s.hideNotice("conflict").wait(200);

    // Keep both edits in your paragraph.
    s.caret(18, LOCAL_EDIT.length).wait(400);
    s.typeNote(" and budget").wait(500);

    // Delete the callout, with the blank line above it.
    s.selectLines(19, 21).wait(700);
    s.key("⌫").wait(100).deleteSelection().wait(300);
    s.noCaret().wait(400);
    s.sync("Project plan.md: pushed. 1 edited, 0 added, 0 removed, 0 comments, 0 replies");
    s.wait(3600);
  },
});
