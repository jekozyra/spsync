# spsync

Edit and comment on SharePoint Word documents as Obsidian notes. Changes sync back to the original `.docx` without rebuilding it, so other people's formatting survives.

## How it works

- `pull` downloads a `.docx` through Microsoft Graph and writes a Markdown note. The original file and a block map are kept in `<vault>/.spsync/`.
- `push` compares the note with what was pulled and patches only the changed paragraphs into the original file. Unchanged paragraphs are byte-for-byte untouched. Within an edited paragraph, unchanged words keep their original formatting.
- `--suggest` sends edits as Word tracked changes, so the owner can accept or reject them.
- Uploads use the file's eTag. If someone changed the document since your pull, `sync` does a three-way merge by paragraph. Overlapping edits show up as `[!conflict]` callouts.

## Comments

Comments appear as callouts under the paragraph they're attached to:

```markdown
> [!comment] Alice Smith · 2025-06-02 · id:3
> Can we tighten this?
```

- New comment: add `> [!comment] your text` under a paragraph.
- Reply: add `> [!reply] re:3` with your text on the following `>` lines.
- Resolve: add `· resolved` to the comment header.

## What Obsidian can't safely edit

Tables, images, fields, content controls, footnotes, and paragraphs with pending tracked changes are shown but locked. Edits to them are skipped with a warning. Pending tracked changes show as `==inserted==` and `~~deleted~~`. Notes inside `%% ... %%` stay private and are never uploaded.

## Setup

```sh
uv tool install --editable ~/projects/spsync
spsync login            # browser sign-in; add --device for a device code
```

Sign-in uses the Microsoft Graph Command Line Tools public client and asks for `Files.ReadWrite.All`, `Sites.Read.All`, and `User.Read`. If the tenant blocks it, register an app and set `SPSYNC_CLIENT_ID` (and `SPSYNC_TENANT`). Tokens are cached in the macOS Keychain.

Obsidian plugin:

```sh
cd obsidian-plugin && pnpm install && pnpm run build
cp main.js manifest.json <vault>/.obsidian/plugins/spsync/
```

Then enable **SharePoint Sync** under Settings > Community plugins.

## CLI

```sh
spsync search budget memo          # find Word docs; then `spsync pull 2`
spsync recent
spsync pull <link> [--out note.md]
spsync sync note.md [--suggest]    # pull, merge, and push as needed
spsync push note.md --dry-run
spsync new note.md --folder <folder link | me>
spsync status --remote
spsync watch --vault <vault>       # keep every linked note in sync
spsync open note.md                # escape hatch: open in the browser
```

## Development

```sh
uv run pytest
uv run python scripts/word_fixtures.py ~/Documents/spsync-check   # then open in Word
osascript scripts/word_check.applescript ~/Documents/spsync-check/1-direct.docx
```
