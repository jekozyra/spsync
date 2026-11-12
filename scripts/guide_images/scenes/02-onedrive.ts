/* Step 2: add a SharePoint library to OneDrive, then open the library folder in Finder. */
import { scene } from "../scene.ts";
import type { FinderWindow, LibraryWindow, State } from "../state.ts";

function library(): LibraryWindow {
  return {
    rows: [
      { name: "Budget draft.docx", modified: "May 9", by: "Sam Lee" },
      { name: "Meeting notes.docx", modified: "May 11", by: "Alice Smith" },
      { name: "Project plan.docx", modified: "May 12", by: "Alice Smith" },
    ],
    hover: null,
    toast: 0,
    toastText: "Shortcut added to My files.",
  };
}

function finder(): FinderWindow {
  return {
    title: "OneDrive - SampleOrg",
    sidebar: [
      { heading: "Favorites" },
      { name: "Desktop" },
      { name: "Documents" },
      { name: "Downloads" },
      { heading: "Locations" },
      { name: "OneDrive - SampleOrg", cloud: true, selected: true },
    ],
    rows: [
      { name: "Personal", kind: "Folder", dir: true },
      { name: "Sample Team - Documents", kind: "Folder", dir: true },
    ],
    selected: -1,
    path: ["Users", "alex", "Library", "CloudStorage", "OneDrive-SampleOrg"],
  };
}

const LIBRARY_FOLDER = "Sample Team - Documents";

scene<State>({
  holdEndMs: 2000,
  geometry: { finder: "inset:44px 70px 30px 90px" },
  init: (st) => ({ ...st, layers: { browser: { o: 1, s: 1, blur: 0 } }, order: ["browser"], library: library(), finder: finder() }),
  script: (s) => {
    s.wait(400).pointerAt({ x: 420, y: 330 });
    s.move("sync", 700).set((st) => {
      if (st.library) st.library.hover = "sync";
    });
    s.wait(700).move("shortcut", 420);
    s.set((st) => {
      if (st.library) st.library.hover = "shortcut";
    });
    s.wait(250).click("shortcut");
    s.span(
      220,
      (st, p) => {
        if (st.library) st.library.toast = p;
      },
      "out",
    ).wait(1600);
    s.span(
      150,
      (st, p) => {
        if (st.library) st.library.toast = 1 - p;
      },
      "out",
    );
    s.set((st) => {
      if (st.library) st.library.hover = null;
    });
    s.hidePointer().wait(300);

    s.switchTo("finder").wait(500);
    s.pointerAt({ x: 560, y: 380 }).move("row-1", 600).click("row-1");
    s.set((st) => {
      if (st.finder) st.finder.selected = 1;
    });
    s.wait(120).click("row-1").wait(250);
    s.set((st) => {
      if (!st.finder) return;

      st.finder.title = LIBRARY_FOLDER;
      st.finder.rows = [
        { name: "Budget draft.docx", kind: "Word document" },
        { name: "Meeting notes.docx", kind: "Word document" },
        { name: "Project plan.docx", kind: "Word document" },
      ];
      st.finder.selected = -1;
      st.finder.path = [...st.finder.path, LIBRARY_FOLDER];
    });
    s.hidePointer();
  },
});
