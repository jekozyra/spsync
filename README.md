# spsync

Edit and comment on SharePoint Word documents as Obsidian notes. Changes sync back to the original `.docx` without rebuilding it, so other people's formatting survives.

## Overview

A pull turns a `.docx` into a Markdown note. spsync keeps the original file and a block map in `<vault>/.spsync/`. A push compares the note with the pulled copy and patches only the changed paragraphs into the original. Unchanged paragraphs stay byte-for-byte identical, and unchanged words keep their formatting. Edits can go out as Word tracked changes. If the document changed since your pull, a sync merges the two versions paragraph by paragraph and marks overlapping edits with `[!conflict]` callouts.

spsync reaches a document in one of two ways:

- **OneDrive sync folder.** spsync reads and writes the files that the OneDrive app syncs to `~/Library/CloudStorage/OneDrive-*`.
- **Word app.** spsync uses the signed-in Word for Mac app for links that OneDrive does not sync. Co-authoring and tracked changes then work as they do in Word.

![Data flow: SharePoint syncs to the local .docx through the OneDrive app and to the Word app. The spsync CLI pulls from both, writes the Obsidian note, and keeps the original .docx and block map in .spsync/. A push patches the changed paragraphs into the local .docx, or replays the edits in the Word app. The Obsidian plugin downloads the standalone CLI from the GitHub release and runs it.](docs/images/data-flow.svg)

The Obsidian plugin, **SharePoint Sync**, runs the spsync command-line tool (CLI) for you. You do not use Terminal.

## Setup

You need:

- A Mac with Apple silicon. spsync does not support Intel Macs.
- Obsidian.
- Microsoft Word for Mac, signed in with your work account.
- The OneDrive app, signed in with your work account.

Do these steps once:

1. In Obsidian, open Settings > Community plugins. Install the **BRAT** plugin, and enable it.
2. Open the command palette, and run the BRAT command **Add a beta plugin for testing**. Enter `jekozyra/spsync`. BRAT installs and enables **SharePoint Sync** from the latest GitHub release.
3. Wait for the "Downloading the spsync CLI" notice to close. The plugin downloads the CLI of the same version from the GitHub release. The plugin checks the SHA-256 checksum of the download and does not run a download that fails the check.
4. Make a SharePoint library available to OneDrive. Open the library in the browser, and click **Sync** or **Add shortcut to My files**.
5. Open the command palette, and run **Check setup**. The result shows a pass or fail line for each check: the OneDrive folder, Word for Mac, the macOS Automation permission to control Word, and the author name. Each failed line includes one fix.

The Automation check starts Word when Word is closed. The first check can show a macOS prompt that asks to let Obsidian control Word. Allow the request.

Your name on comments and tracked changes comes from your macOS full name. To use another name, set **Author name** in the SharePoint Sync settings.

## Upgrade

BRAT checks for a new release each time Obsidian starts, and installs it. To upgrade at once, run the BRAT command **Check for updates to all beta plugins and UPDATE**.

After an upgrade, the plugin downloads the CLI of the new version. Every vault uses the same CLI in `~/Library/Application Support/spsync/bin/<version>/`. The plugin removes the older versions.

## Usage

Run these commands from the command palette:

| Command | What it does |
|---|---|
| Find and open a SharePoint document | Search by name, and pull the document into a note |
| Open a recent SharePoint document | Pull a document from your recent files |
| Open a SharePoint link | Pull the document at a pasted link |
| Sync this note | Pull, merge, and push the current note |
| Send edits as tracked changes | Push the edits in the current note as Word tracked changes |
| Sync all linked notes | Sync every note that came from SharePoint |
| Open this document in SharePoint | Open the document in the browser |
| Create a Word document from this note | Create a new `.docx` from the current note in a synced folder that you choose |
| Comment on this paragraph | Add a comment callout under the paragraph |
| Reply to this comment | Add a reply callout under the comment |
| Check setup | Show the setup checks |

The ribbon button **Sync with SharePoint** syncs the current note. By default, the plugin pushes your edits 30 seconds after you stop typing, and pulls SharePoint changes every 5 minutes.

### Documents that other people own

Turn on **Send edits as tracked changes** in the SharePoint Sync settings before you edit a document that someone else owns. Every push, including the automatic push, then sends your edits as tracked changes. The owner accepts or rejects each change in Word.

### Comments

Comments appear as callouts under the paragraph that they belong to:

```markdown
> [!comment] Alice Smith · 2025-06-02 · id:3
> Can we tighten this?
```

To add a comment, write `> [!comment] your text` under a paragraph. To reply, write `> [!reply] re:3`, and put your text on the next `>` lines. To resolve a comment, add `· resolved` to the comment header. spsync cannot thread or resolve comments in a document that it opens through the Word app. For those documents, spsync posts each reply as a "Re <name>:" comment. Resolve those comments in Word.

### Conflicts

When you and another person change the same paragraph, the sync keeps your text and adds a `[!conflict]` callout with the SharePoint version under the paragraph. Edit the paragraph to the text that you want, delete the callout, and sync again. spsync does not push a note that still has a `[!conflict]` callout.

### Locked content and private notes

Tables, images, fields, content controls, footnotes, and paragraphs with pending tracked changes appear in the note but are locked. spsync skips an edit to locked content and shows a warning. Pending tracked changes appear as `==inserted==` and `~~deleted~~`.

Text inside `%% ... %%` stays in the note. spsync never uploads it.

### Settings

The SharePoint Sync settings tab sets the author name, automatic sync, the idle time before a push, the interval between checks for SharePoint changes, and whether edits go out as tracked changes.

## Contributing

Issues are welcome. Open an issue to report a bug or to ask for a feature. The project does not accept pull requests from people outside the team. [`CONTRIBUTING.md`](CONTRIBUTING.md) describes the developer setup, the CLI, and the checks.

## Maintainers

Jillian Kozyra ([@jekozyra](https://github.com/jekozyra)) maintains spsync.

## License

spsync is released under the MIT license. See [`LICENSE`](LICENSE).

spsync depends on [`merge3`](https://pypi.org/project/merge3/), which is licensed under GPL-2.0-or-later. The repository declares `merge3` as a dependency and does not include its code.

The standalone CLI archive in each GitHub release bundles `merge3` and the other dependencies. The archive includes `THIRD_PARTY_NOTICES.md`, which lists each bundled package and its license, and the `licenses/` folder with the license files. Because of the GPL license of `merge3`, each release also publishes `spsync-X.Y.Z-source.tar.gz`, the complete corresponding source code of the archive: the spsync source at the release tag and the source distribution of each bundled package.

The vendored Oxlint rules in `obsidian-plugin/tools/oxlint/anti-slop/` keep their own MIT license files. [`UPSTREAM.md`](obsidian-plugin/tools/oxlint/anti-slop/UPSTREAM.md) names their source.
