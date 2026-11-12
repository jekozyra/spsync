/**
 * Render each Mermaid diagram in `docs/images/` to SVG with Pele. GitHub renders a `mermaid` code block
 * with Mermaid.js, so the README shows the committed SVG as an image instead.
 *
 * ```text
 * docs/images/<name>.mmd --render--> docs/images/<name>.svg
 * ```
 *
 * `node diagrams.ts` writes every SVG. `node diagrams.ts --check` writes nothing, and exits with code 1
 * when an SVG is missing or differs from the render of its source.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import * as path from "node:path";

import { render } from "pele";

const IMAGES_DIR = path.join(import.meta.dirname, "..", "docs", "images");
const SOURCE_EXTENSION = ".mmd";
const CHECK_FLAG = "--check";

// GitHub shows the SVG as an image, so the page CSS cannot set the Pele variables. The SVG carries its
// own dark colors, which follow the color scheme of the browser.
const DARK_THEME =
  "<style>@media (prefers-color-scheme: dark){.pele{" +
  "--pele-bg:#0d1117;--pele-fg:#e6edf3;--pele-muted:#9198a1;--pele-line:#e6edf3;" +
  "--pele-surface:#151b23;--pele-surface-alt:#212830;--pele-border:#3d444d}}</style>";

function renderDiagram(source: string): string {
  // A narrow GitHub page scales the image down, so the diagram keeps the direction of its source.
  const { svg } = render(source, { autoDirection: false });
  const openingTagEnd = svg.indexOf(">") + 1;

  return `${svg.slice(0, openingTagEnd)}${DARK_THEME}${svg.slice(openingTagEnd)}\n`;
}

const check = process.argv.includes(CHECK_FLAG);
const staleImages: string[] = [];

for (const file of readdirSync(IMAGES_DIR)) {
  if (!file.endsWith(SOURCE_EXTENSION)) {
    continue;
  }

  const svgPath = path.join(IMAGES_DIR, `${path.basename(file, SOURCE_EXTENSION)}.svg`);
  const svg = renderDiagram(readFileSync(path.join(IMAGES_DIR, file), "utf8"));

  if (!check) {
    writeFileSync(svgPath, svg);
  } else if (!existsSync(svgPath) || readFileSync(svgPath, "utf8") !== svg) {
    staleImages.push(path.relative(process.cwd(), svgPath));
  }
}

if (staleImages.length > 0) {
  console.error(
    `These diagrams differ from their Mermaid source: ${staleImages.join(", ")}. Run pnpm -C obsidian-plugin run diagrams.`,
  );
  process.exitCode = 1;
}
