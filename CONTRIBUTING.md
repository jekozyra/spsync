# Contributing to spsync

This document is for people who develop spsync. [`README.md`](README.md) describes how to install and use the plugin. [`CODING_STANDARDS.md`](CODING_STANDARDS.md) lists the mandatory coding standards and checks.

## Setup

You need macOS, [uv](https://docs.astral.sh/uv/) with Python 3.13, and either the OneDrive app (local backend) or Word for Mac (word backend). The Obsidian plugin also needs Node 23.6 or later and pnpm.

From a clone of this repo, install the CLI:

```sh
uv tool install --editable .
spsync mode            # shows the backend, author name, and search roots
```

Check the setup. `spsync doctor` prints a pass or fail line for the CLI version, the OneDrive folder, Word for Mac, the macOS Automation permission to control Word, and the author name. Each fail line includes one fix. The command exits with code 3 when a required check fails, and `--json` prints the same results for the plugin. The Automation check starts Word hidden when Word is closed, and quits Word after the check. The first run can show the macOS permission prompt. Allow the request so that spsync can control Word.

```sh
spsync doctor
```

Install the git hooks once. The pre-commit hook runs ruff, ty, anti-slop-python, pytest, and the plugin's Oxfmt, Oxlint, test, and build checks. When a commit changes `pyproject.toml`, `obsidian-plugin/manifest.json`, or `obsidian-plugin/package.json`, the hook also runs `scripts/check_versions.py`, which fails when the three versions differ.

```sh
uv sync --locked
uv run lefthook install
```

### Run the plugin from a clone

Build the Obsidian plugin and copy it into your vault:

```sh
cd obsidian-plugin && pnpm install --frozen-lockfile && pnpm run build
mkdir -p <vault>/.obsidian/plugins/spsync
cp main.js manifest.json <vault>/.obsidian/plugins/spsync/
```

Then enable **SharePoint Sync** under Settings > Community plugins. To run the CLI from your clone instead of the downloaded build, set the plugin's **spsync CLI path** setting to `~/.local/bin/spsync`. A non-empty path skips the download.

## CLI usage

Run these from your vault, or pass `--vault` (or set `SPSYNC_VAULT`):

```sh
spsync search budget memo          # find Word docs; then `spsync pull 2`
spsync recent
spsync pull <link> [--out note.md]
spsync sync note.md [--suggest]    # pull, merge, and push as needed
spsync push note.md --dry-run      # show what would change without uploading
spsync new note.md --folder <folder link | me>
spsync status --remote
spsync watch                       # keep every linked note in sync
spsync open note.md                # open the document in the browser
spsync unlink note.md
spsync --version                   # print the CLI version
```

`--suggest` sends edits as Word tracked changes. Use `--suggest` and `push --dry-run` on documents that other people own.

### Backends

spsync reaches documents through one of three backends:

- **local** (default) works on files the OneDrive app syncs to `~/Library/CloudStorage/OneDrive-*`. It needs no Graph consent.
- **word** is used automatically for links that are not synced locally. It drives the signed-in Word app. The word backend cannot script threading or resolving comments.
- **graph** talks to Microsoft Graph directly and needs tenant consent.

To use the graph backend, sign in and switch to it:

```sh
spsync login           # browser sign-in; add --device for a device code
spsync mode graph
```

## Configuration

Set the backend, the author name used on comments, and the folders to search:

```sh
spsync mode local --author "Name" --root <folder>
```

Settings live in `~/.config/spsync/`. Graph tokens are cached in the macOS Keychain. Sign-in uses the Microsoft Graph Command Line Tools client and asks for `Files.ReadWrite.All`, `Sites.Read.All`, and `User.Read`. If your tenant blocks that client, register an app and set `SPSYNC_CLIENT_ID`.

| Variable | Purpose |
|---|---|
| `SPSYNC_VAULT` | Default vault (otherwise the current directory) |
| `SPSYNC_BACKEND` | Override the backend (`local` or `graph`) |
| `SPSYNC_ROOTS` | Search roots, separated by `:` |
| `SPSYNC_CLIENT_ID`, `SPSYNC_TENANT` | Custom Graph app registration |
| `SPSYNC_CONFIG_DIR` | Config location (default `~/.config/spsync`) |

The plugin's author name setting runs `spsync mode --author`, so the CLI uses the same name.

## Project structure

| Path | What lives here |
|---|---|
| `src/spsync/` | The CLI: `cli.py` commands, `config.py` settings, `reader/` and `patch/` docx parsing and patching, `local.py`, `word/`, and `graph.py` backends |
| `obsidian-plugin/` | The Obsidian plugin, which shells out to the CLI and downloads the standalone CLI in `standalone-cli.ts` |
| `scripts/` | The standalone build, the manifest version check, and helpers that generate Word fixtures and check them in Word |
| `tests/` | pytest suite and `.docx` fixtures |
| `docs/` | The illustrated guide in `guide.md`, the guide animations and the README diagrams in `images/`, and the issue tracker notes for agents |
| `.github/workflows/` | The release workflow, which publishes a GitHub release for each version tag |

## Checks

Run the tests, and check fixtures against real Word:

```sh
uv run pytest
uv run python scripts/word_fixtures.py ~/Documents/spsync-check   # then open in Word
osascript scripts/word_check.applescript ~/Documents/spsync-check/1-direct.docx
```

## Diagrams

[Pele](https://pele.run/) renders the README diagrams. GitHub renders a `mermaid` code block with Mermaid.js, so the README shows the committed SVG as an image. To change a diagram, edit its Mermaid source in `docs/images/<name>.mmd`, and write the SVG again:

```sh
pnpm -C obsidian-plugin run diagrams
```

Commit the `.mmd` and the `.svg` together. The pre-commit hook runs `diagrams:check`, which fails when an SVG differs from its source.

## Build and release

To build the standalone CLI, which runs without Python or uv, run the build script on a Mac with Apple silicon. The script needs the Xcode Command Line Tools and writes `dist/spsync-macos-<arch>.tar.gz`:

```sh
scripts/build_standalone.sh
```

To publish a release, follow [`RELEASING.md`](RELEASING.md). [`CHANGELOG.md`](CHANGELOG.md) records the changes in each release.
