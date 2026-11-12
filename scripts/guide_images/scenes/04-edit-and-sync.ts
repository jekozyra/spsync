/* Step 4: edit a paragraph, then sync the note. */
import { scene } from "../scene.ts";
import { withLinkedNote, type State } from "../state.ts";

scene<State>({
  holdEndMs: 1800,
  init: (st) => withLinkedNote(st),
  script: (s) => {
    s.wait(600).caret(2).wait(400);
    s.typeNote(" I added this sentence in Obsidian.").wait(500);
    s.noCaret().wait(500);
    s.sync("Project plan.md: pushed. 1 edited, 0 added, 0 removed, 0 comments, 0 replies");
    s.wait(3600);
  },
});
