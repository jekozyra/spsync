# spsync

Edit and comment on SharePoint Word documents as Obsidian notes. Changes sync back to the original `.docx` without rebuilding it, so other people's formatting survives.

## Overview

`pull` turns a `.docx` into a Markdown note and keeps the original file plus a block map in `<vault>/.spsync/`. `push` compares the note with what was pulled and patches only the changed paragraphs into the original, so unchanged paragraphs stay byte-for-byte identical and unchanged words keep their formatting. With `--suggest`, edits arrive as Word tracked changes. If the document changed since your pull, `sync` does a three-way merge by paragraph and marks overlapping edits with `[!conflict]` callouts.

spsync reaches documents through one of three backends:

- **local** (default) works on files the OneDrive app syncs to `~/Library/CloudStorage/OneDrive-*`. It needs no Graph consent. To reach a SharePoint library, open it in the browser and click **Sync** or **Add shortcut to My files**.
- **word** is used automatically for links that are not synced locally. It drives the signed-in Word app, so co-authoring and tracked changes behave as they do in Word.
- **graph** talks to Microsoft Graph directly and needs tenant consent.

## Setup

### Install the plugin only

Teammates need only a Mac with Apple silicon, Obsidian, and either the OneDrive app or Word for Mac. They do not need Terminal, Python, uv, or Node.

1. In Obsidian, install the **BRAT** plugin from Settings > Community plugins, and enable it.
2. Run the BRAT command **Add a beta plugin for testing**, and enter `jekozyra/spsync`. BRAT installs and enables **SharePoint Sync** from the latest GitHub release, and installs later releases as updates.
3. Wait for the "Downloading the spsync CLI" notice to close. On the first start after an install or an update, the plugin downloads the standalone CLI of the same version from the GitHub release. The plugin checks the SHA-256 checksum of the download and does not run a build that fails the check. Every vault uses the same build in `~/Library/Application Support/spsync/bin/<version>/`. After an update, the plugin removes the older versions.
4. Run **Check setup** from the command palette.

The CLI download supports only Macs with Apple silicon. On an Intel Mac, install the CLI from a clone as described below, and set the CLI path in the plugin settings.

### Develop spsync

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

To use the graph backend instead, sign in and switch to it:

```sh
spsync login           # browser sign-in; add --device for a device code
spsync mode graph
```

Build the Obsidian plugin and copy it into your vault:

```sh
cd obsidian-plugin && pnpm install --frozen-lockfile && pnpm run build
mkdir -p <vault>/.obsidian/plugins/spsync
cp main.js manifest.json <vault>/.obsidian/plugins/spsync/
```

Then enable **SharePoint Sync** under Settings > Community plugins. To run the CLI from your clone instead of the downloaded build, set the plugin's **spsync CLI path** setting to `~/.local/bin/spsync`. A non-empty path skips the download. Run **Check setup** from the command palette to see the `spsync doctor` results in Obsidian.

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
spsync --version                   # print the CLI version
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

The plugin's settings tab sets the CLI path, the author name, automatic sync, the idle and polling intervals, and whether edits go out as tracked changes. The author name setting runs `spsync mode --author`, so the CLI uses the same name.

## Project structure

| Path | What lives here |
|---|---|
| `src/spsync/` | The CLI: `cli.py` commands, `config.py` settings, `reader/` and `patch/` docx parsing and patching, `local.py`, `word/`, and `graph.py` backends |
| `obsidian-plugin/` | The Obsidian plugin, which shells out to the CLI and downloads the standalone CLI in `standalone-cli.ts` |
| `scripts/` | The standalone build, the manifest version check, and helpers that generate Word fixtures and check them in Word |
| `tests/` | pytest suite and `.docx` fixtures |
| `.github/workflows/` | The release workflow, which publishes a GitHub release for each version tag |

Install the git hooks once. The pre-commit hook runs ruff, ty, anti-slop-python, pytest, and the plugin's Oxfmt, Oxlint, test, and build checks. When a commit changes `pyproject.toml`, `obsidian-plugin/manifest.json`, or `obsidian-plugin/package.json`, the hook also runs `scripts/check_versions.py`, which fails when the three versions differ. [`CODING_STANDARDS.md`](CODING_STANDARDS.md) lists every check.

```sh
uv sync --locked
uv run lefthook install
```

To run the tests and check fixtures against real Word:

```sh
uv run pytest
uv run python scripts/word_fixtures.py ~/Documents/spsync-check   # then open in Word
osascript scripts/word_check.applescript ~/Documents/spsync-check/1-direct.docx
```

To build the standalone CLI, which runs without Python or uv, run the build script on a Mac of the target architecture. It needs the Xcode Command Line Tools and writes `dist/spsync-macos-<arch>.tar.gz`:

```sh
scripts/build_standalone.sh
```

To publish a release, follow [`RELEASING.md`](RELEASING.md). [`CHANGELOG.md`](CHANGELOG.md) records the changes in each release.

## Contributing

Issues are welcome. Open an issue to report a bug or to ask for a feature. The project does not accept pull requests from people outside the team.

## Maintainers

Jillian Kozyra ([@jekozyra](https://github.com/jekozyra)) maintains spsync.

## License

spsync is released under the MIT license. See [`LICENSE`](LICENSE).

spsync depends on [`merge3`](https://pypi.org/project/merge3/), which is licensed under GPL-2.0-or-later. The repository declares `merge3` as a dependency and does not include its code.

The standalone CLI archive in each GitHub release bundles `merge3` and the other dependencies. The archive includes `THIRD_PARTY_NOTICES.md`, which lists each bundled package and its license, and the `licenses/` folder with the license files. Because of the GPL license of `merge3`, each release also publishes `spsync-X.Y.Z-source.tar.gz`, the complete corresponding source code of the archive: the spsync source at the release tag and the source distribution of each bundled package.

The vendored Oxlint rules in `obsidian-plugin/tools/oxlint/anti-slop/` keep their own MIT license files. [`UPSTREAM.md`](obsidian-plugin/tools/oxlint/anti-slop/UPSTREAM.md) names their source.
