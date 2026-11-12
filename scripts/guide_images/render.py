"""Render the animations of docs/guide.md from the scenes in scripts/guide_images/scenes/.

    uv run --group guide python scripts/guide_images/render.py [SCENE ...] [--out DIR] [--still MS[,MS...]]

Each scene is a TypeScript file that calls `scene()`. A frame is a pure function of time: the page
exposes `window.renderAt(ms)`, and this script seeks to each frame, so a frame never depends on
wall-clock timing.

    scenes/NN-name.ts --renderAt(ms) for each frame--> screenshots --Pillow--> docs/images/NN-name.gif
                      `--renderAt(last frame)--------> screenshot -----------> docs/images/NN-name.png

Chromium cannot run TypeScript. The page loads from a local host name that only exists inside this
script. A Playwright route answers each request from this folder, and Node strips the types from
each .ts file (`module.stripTypeScriptTypes`) before the page receives it.
"""

import argparse
import io
import subprocess
import sys
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import Page, Route, sync_playwright

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
DEFAULT_OUT = HERE.parent.parent / "docs" / "images"

# The guide shows each image 800 pixels wide. Frames render at twice that size for Retina screens.
STAGE_WIDTH_PX = 800
STAGE_HEIGHT_PX = 500
DEVICE_SCALE = 2
FRAME_MS = 40
GIF_COLORS = 256
PALETTE_SAMPLE_FRAMES = 10

# `.invalid` is reserved (RFC 2606), so a request to this host never leaves the machine.
PAGE_ORIGIN = "http://guide.invalid"
CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".ts": "text/javascript"}
STRIP_TYPES_JS = (
    "process.stdout.write(require('node:module').stripTypeScriptTypes(require('node:fs').readFileSync(0, 'utf8')))"
)


@cache
def _javascript(path: Path) -> str:
    """The JavaScript of a TypeScript file. Node 23.6 or later has `module.stripTypeScriptTypes`."""
    result = subprocess.run(
        ["node", "--no-warnings", "-e", STRIP_TYPES_JS],
        input=path.read_text(),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _serve(route: Route) -> None:
    relative = urlparse(route.request.url).path.lstrip("/")
    path = (HERE / relative).resolve()
    content_type = CONTENT_TYPES.get(path.suffix)
    if not path.is_relative_to(HERE) or not path.is_file() or content_type is None:
        route.fulfill(status=404)
        return
    body = _javascript(path) if path.suffix == ".ts" else path.read_text()
    route.fulfill(status=200, content_type=content_type, body=body)


def _open_scene(page: Page, name: str) -> tuple[float, float]:
    """Load a scene, and return its duration and the time of its static frame, in milliseconds."""
    page.goto(f"{PAGE_ORIGIN}/stage.html?scene={name}")
    page.wait_for_function("window.renderAt !== undefined")
    return page.evaluate("window.sceneDurationMs"), page.evaluate("window.sceneStaticAtMs")


def _frame(page: Page, ms: float) -> Image.Image:
    page.evaluate(f"window.renderAt({ms})")
    return Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")


def _palette(frames: list[Image.Image]) -> Image.Image:
    """One palette for every frame, so a color does not change from frame to frame."""
    samples = frames[:: max(1, len(frames) // PALETTE_SAMPLE_FRAMES)]
    width, height = samples[0].size
    sheet = Image.new("RGB", (width, height * len(samples)))
    for k, frame in enumerate(samples):
        sheet.paste(frame, (0, height * k))
    return sheet.quantize(colors=GIF_COLORS, method=Image.Quantize.MEDIANCUT)


def _write_gif(frames: list[Image.Image], path: Path) -> int:
    """Write the frames as a looping GIF. Equal frames merge into one longer frame. Returns the frame count."""
    palette = _palette(frames)
    merged: list[Image.Image] = []
    durations: list[int] = []
    for frame in frames:
        indexed = frame.quantize(palette=palette, dither=Image.Dither.NONE)
        if merged and indexed.tobytes() == merged[-1].tobytes():
            durations[-1] += FRAME_MS
        else:
            merged.append(indexed)
            durations.append(FRAME_MS)
    merged[0].save(path, save_all=True, append_images=merged[1:], duration=durations, loop=0, optimize=True, disposal=1)
    return len(merged)


def render(page: Page, name: str, out: Path) -> None:
    duration_ms, static_ms = _open_scene(page, name)
    times = [min(ms, duration_ms) for ms in range(0, int(duration_ms) + FRAME_MS, FRAME_MS)]
    count = _write_gif([_frame(page, ms) for ms in times], out / f"{name}.gif")
    _frame(page, static_ms).save(out / f"{name}.png")
    size_kib = (out / f"{name}.gif").stat().st_size // 1024
    print(f"{name}: {duration_ms / 1000:.1f} s, {count} frames, {size_kib} KiB")


def render_stills(page: Page, name: str, times_ms: list[int], out: Path) -> None:
    """Write single frames, for a check of a scene while you edit it."""
    _open_scene(page, name)
    for ms in times_ms:
        path = out / f"{name}-{ms}ms.png"
        _frame(page, ms).save(path)
        print(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenes", nargs="*", help="scene names, such as 05-comments (default: every scene)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: docs/images)")
    parser.add_argument("--still", help="write only the frames at these comma-separated times in milliseconds")
    args = parser.parse_args()
    names = args.scenes or sorted(p.stem for p in SCENES.glob("*.ts"))
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": STAGE_WIDTH_PX, "height": STAGE_HEIGHT_PX}, device_scale_factor=DEVICE_SCALE
        )
        page.on("pageerror", lambda error: print(f"page error: {error}", file=sys.stderr))
        page.route(f"{PAGE_ORIGIN}/**", _serve)
        for name in names:
            if args.still:
                render_stills(page, name, [int(ms) for ms in args.still.split(",")], args.out)
            else:
                render(page, name, args.out)
        browser.close()


if __name__ == "__main__":
    main()
