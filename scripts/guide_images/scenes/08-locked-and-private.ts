/* Step 8: private notes in %% ... %% stay local, and edits to locked content are skipped. */
import { scene } from "../scene.ts";
import { withLinkedNote, type State } from "../state.ts";

const DETAILS_SCROLL_PX = 171;
const NOTHING_TO_SEND = "Project plan.md: unchanged. Nothing to send.";
// The warning that the patcher writes for an edit to a locked block (src/spsync/patch/patcher.py).
const TABLE_WARNING = "  warning: Skipped edit to a block Obsidian can't safely change (table): | A | B | | --- | --- | | 1 | 2 |";

scene<State>({
  holdEndMs: 1800,
  init: (st) => ({ ...withLinkedNote(st, { props: false }), scroll: DETAILS_SCROLL_PX }),
  script: (s) => {
    // A private note in %% ... %% is never uploaded, so the sync has nothing to send.
    s.wait(500).caret(18).wait(300);
    s.typeNote("\n\n%% Ask Alice about the budget before Friday. %%").wait(500);
    s.noCaret().wait(400);
    s.sync(NOTHING_TO_SEND);
    s.wait(3600);

    // A table is locked: the sync skips the edit and shows a warning.
    s.caret(16, "| 1 | 2".length).wait(300);
    s.backspace(1).typeNote("3").wait(400);
    s.noCaret().wait(400);
    s.sync(`${NOTHING_TO_SEND}\n${TABLE_WARNING}`);
    s.wait(3600);
  },
});
