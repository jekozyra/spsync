# spsync

Edit and comment on SharePoint Word documents as Obsidian notes. Changes sync back to the original `.docx` without rebuilding it, so other people's formatting survives.

## Overview

`pull` turns a `.docx` into a Markdown note and keeps the original file plus a block map in `<vault>/.spsync/`. `push` compares the note with what was pulled and patches only the changed paragraphs into the original, so unchanged paragraphs stay byte-for-byte identical and unchanged words keep their formatting. With `--suggest`, edits arrive as Word tracked changes. If the document changed since your pull, `sync` does a three-way merge by paragraph and marks overlapping edits with `[!conflict]` callouts.

spsync reaches documents through one of three backends:

- **local** (default) works on files the OneDrive app syncs to `~/Library/CloudStorage/OneDrive-*`. It needs no Graph consent. To reach a SharePoint library, open it in the browser and click **Sync** or **Add shortcut to My files**.
- **word** is used automatically for links that are not synced locally. It drives the signed-in Word app, so co-authoring and tracked changes behave as they do in Word.
- **graph** talks to Microsoft Graph directly and needs tenant consent.

## Setup

You need macOS, [uv](https://docs.astral.sh/uv/) with Python 3.13, and either the OneDrive app (local backend) or Word for Mac (word backend). The Obsidian plugin also needs Node and pnpm.

From a clone of this repo, install the CLI:

```sh
uv tool install --editable .
spsync mode            # shows the backend, author name, and search roots
```

To use the graph backend instead, sign in and switch to it:

```sh
spsync login           # browser sign-in; add --device for a device code
spsync mode graph
```

Build the Obsidian plugin and copy it into your vault:

```sh
cd obsidian-plugin && pnpm install && pnpm run build
mkdir -p <vault>/.obsidian/plugins/spsync
cp main.js manifest.json <vault>/.obsidian/plugins/spsync/
```

Then enable **SharePoint Sync** under Settings > Community plugins.

## Usage

Run these from your vault, or pass `--vault` (or set `SPSYNC_VAULT`):

```sh
spsync search budget memo          # find Word docs; then `spsync pull 2`
spsync recent
spsync pull <link> [--out note.md]
spsync sync note.md [--suggest]    # pull, merge, and push as needed
spsync push note.md --dry-run
spsync new note.md --folder <folder link | me>
spsync status --remote
spsync watch                       # keep every linked note in sync
spsync open note.md                # open the document in the browser
spsync unlink note.md
```

In Obsidian, the same actions are available from the command palette ("Find and open a SharePoint document", "Sync this note", "Comment on this paragraph", and so on).

### Comments

Comments appear as callouts under the paragraph they belong to:

```markdown
> [!comment] Alice Smith · 2025-06-02 · id:3
> Can we tighten this?
```

To add a comment, write `> [!comment] your text` under a paragraph. To reply, write `> [!reply] re:3` with your text on the following `>` lines. To resolve, add `· resolved` to the comment header. The word backend cannot script threading or resolving, so it posts replies as "Re <name>:" comments and leaves resolving to Word.

### Locked content

Tables, images, fields, content controls, footnotes, and paragraphs with pending tracked changes are shown but locked, and edits to them are skipped with a warning. Pending tracked changes appear as `==inserted==` and `~~deleted~~`. Text inside `%% ... %%` stays private and is never uploaded.

## Configuration

Set the backend, the author name used on comments, and the folders to search:

```sh
spsync mode local --author "Name" --root <folder>
```

Settings live in `~/.config/spsync/`. Graph tokens are cached in the macOS Keychain. Sign-in uses the Microsoft Graph Command Line Tools client and asks for `Files.ReadWrite.All`, `Sites.Read.All`, and `User.Read`; if your tenant blocks it, register an app and set `SPSYNC_CLIENT_ID`.

| Variable | Purpose |
|---|---|
| `SPSYNC_VAULT` | Default vault (otherwise the current directory) |
| `SPSYNC_BACKEND` | Override the backend (`local` or `graph`) |
| `SPSYNC_ROOTS` | Search roots, separated by `:` |
| `SPSYNC_CLIENT_ID`, `SPSYNC_TENANT` | Custom Graph app registration |
| `SPSYNC_CONFIG_DIR` | Config location (default `~/.config/spsync`) |

The plugin's settings tab sets the CLI path, automatic sync, the idle and polling intervals, and whether edits go out as tracked changes.

## Project structure

| Path | What lives here |
|---|---|
| `src/spsync/` | The CLI: `cli.py` commands, `reader.py`/`patch.py` docx parsing and patching, `local.py`/`word.py`/`graph.py` backends |
| `obsidian-plugin/` | The Obsidian plugin, which shells out to the CLI |
| `scripts/` | Helpers that generate Word fixtures and check them in Word |
| `tests/` | pytest suite and `.docx` fixtures |

To run the tests and check fixtures against real Word:

```sh
uv run pytest
uv run python scripts/word_fixtures.py ~/Documents/spsync-check   # then open in Word
osascript scripts/word_check.applescript ~/Documents/spsync-check/1-direct.docx
```
