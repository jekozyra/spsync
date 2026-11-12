# Changelog

This file records the notable changes in each spsync release. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The release workflow publishes the section of each version as the release notes. [`RELEASING.md`](RELEASING.md) describes the release steps.

## [Unreleased]

### Added

- `spsync pull`, `push`, and `sync` edit a SharePoint Word document as an Obsidian note. The merge keeps unchanged paragraphs and their formatting, and shows overlapping edits as conflict callouts.
- Word comments and replies appear as callouts under their paragraphs. New callouts become Word comments on push.
- Tables, images, fields, and other locked content appear in the note and stay unchanged in the document.
- Three backends: OneDrive-synced files (local), the Word for Mac app (word), and Microsoft Graph (graph).
- `spsync search`, `recent`, `new`, `status`, `watch`, `open`, and `unlink`.
- `spsync doctor` checks the first-run setup: the OneDrive folder, Word for Mac, the Automation permission, and the author name.
- `spsync --version` prints the CLI version.
- The Obsidian plugin runs the CLI from the command palette, syncs notes automatically, and has a Check setup command and an author setting.
- A standalone build of the CLI for Apple silicon Macs. The build needs no Python or uv, and includes the license notices of its bundled packages.
