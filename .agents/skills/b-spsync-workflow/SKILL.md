---
name: b-spsync-workflow
description: spsync development workflow. Use when branching, committing, planning, filing issues, or opening PRs in jekozyra/spsync. Covers issue-numbered branch naming, scoped PR titles, template-driven PR and issue bodies, conventional commits, local-only plans, GitHub Issues tracking, and stacc stacking.
---

# spsync Development Workflow

## Purpose

Define project-specific conventions for branches, PRs, and issues. These conventions override `b-development-workflow` in spsync.

## Templates

The templates own the section headings for issues and PR descriptions. This skill owns the guidance for each section.

- **Issue:** [`.github/ISSUE_TEMPLATE/ticket.md`](../../../.github/ISSUE_TEMPLATE/ticket.md). Create an issue with `gh issue create --template Ticket`. The `--template` flag matches the `name` field in the template front matter, not the file name. [`.github/ISSUE_TEMPLATE/config.yml`](../../../.github/ISSUE_TEMPLATE/config.yml) turns off blank issues for users with the Read or Triage role. GitHub still shows a "Blank issue" option, labeled "Maintainers only", to users with the Write role or higher.
- **PR description:** [`.github/pull_request_template.md`](../../../.github/pull_request_template.md). GitHub fills a new PR on the web with this template. `stacc submit` and `gh pr create` do not apply the template. Write the body to a temporary file that uses the template sections, and pass it with `stacc submit --description @<path>`.

Each template starts with a comment that copies the prose rules, the em-dash rule, and the quotation mark rule from [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md). When these rules in `CODING_STANDARDS.md` change, change the copies in both templates.

## Branch Naming

- **Pattern:** `jillian/<NN>-<short-desc>`, where `NN` is the GitHub issue number. Give each branch a distinct description.
- Descriptions are lowercase and hyphenated.

Examples: `jillian/12-word-backend-retry`, `jillian/07-graph-comment-threads`.

## PR Title Format

Use a conventional commit with a required scope and no ticket prefix: `<type>(<scope>): <description>`.

- Use the types and scopes from **Commit Conventions**. The scope is required in PR titles.
- Write the description in imperative mood and lowercase, with no period, and keep it under 72 characters.
- Keep titles independent of transient tracker identifiers; the PR body describes the lasting behavior.

Example: `feat(word): retry Word saves on lock`.

## PR Description Format

Use exactly the sections in [`.github/pull_request_template.md`](../../../.github/pull_request_template.md), in the template order. Add no other sections. Delete the prose-rules comment from the body.

Use practical ASD-STE100 Simplified Technical English principles for prose.

- **Goal:** one or two sentences on the outcome and why it matters.
- **Summary:** the meaningful changes, synthesized rather than listed commit by commit. Explain motivation in prose that stands on its own after the issue closes. When the change touches docx reading or patching, state which document content it can affect, such as run formatting, comments, or locked content.
- **Testing:** the automated checks added or run and any manual verification needed, or a brief justification when no testing was needed. Name a manual check against Word for Mac, OneDrive, or Obsidian when the change needs one.
- **Issue:** `Closes #NN` on the PR that completes the GitHub issue, so the merge closes it; `Refs #NN` on earlier PRs for the same issue.

## Commit Conventions

Use conventional commits: `<type>(<scope>): <description>`. The scope is optional in commits and required in PR titles.

- **Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `chore`, `perf`, `revert`.
- **Scopes:**
  - `cli` for `src/spsync/cli.py`.
  - `core` for `core.py`, `store.py`, and `mdparse.py`: pull, push, sync, merge, and note parsing.
  - `reader` for `reader.py` and `inline.py`: docx to Markdown.
  - `patch` for `patch.py` and `ooxml.py`: Markdown changes written back into the docx.
  - `local`, `word`, and `graph` for the backends. `graph` also covers `auth.py`.
  - `plugin` for `obsidian-plugin/`.
  - `docs` for the README and repository prose.
  - `tooling` for `pyproject.toml`, `scripts/`, `.github/`, and agent files.
  - If a change spans scopes, split it into separate commits or use the primary scope.
- Write the description in imperative mood and lowercase, with no period and no ticket prefix.
- Keep commits small and atomic, and prefer new commits over amending.
- Add a body only for a non-obvious reason, and wrap it at 72 columns.

Example: `fix(patch): keep run formatting on split paragraphs`.

Before each commit, inspect the complete staged change:

```bash
git diff --cached --name-status
git diff --cached --stat
```

Confirm that every staged path belongs to the commit scope. Unstage unrelated paths before committing.

## Plans

Plans are local and uncommitted or captured in ticket comments.

- Write implementation plans to `.dev/plans/<NN>-<short-desc>.md`. `.dev/` is gitignored.
- Write the plan before implementation and update it as work progresses. Never commit it.
- The GitHub issue owns scope and acceptance criteria. Record a scope or dependency change in the issue, not only in a plan.

## Tracker

The tracker is GitHub Issues in `jekozyra/spsync`. Use `gh issue` to create, view, edit, and comment on issues. No tracker MCP server is needed.

- A ticket is a GitHub issue that states what to build, its acceptance criteria, and the issues that block it, as `Blocked by #NN` lines in the body.
- **Ticket continuity:** A PR split or additional work needed to make the original ticket feature complete remains part of the original issue. Create no new issue for that work. Give every resulting branch the original issue's `NN` prefix.
- Close an issue through the `Closes #NN` line under **Issue** in the PR that completes it.
- Planning skills read tracker operations from [`docs/agents/issue-tracker.md`](../../../docs/agents/issue-tracker.md).

## Issue Title Format

Use `<scope>: <description>`.

- Use the commit scopes from **Commit Conventions**.
- Write the description in imperative mood and lowercase, with no period, and keep it under 72 characters.

Example: `word: retry saves when the document is locked`.

## Issue Body Format

Use exactly the sections in [`.github/ISSUE_TEMPLATE/ticket.md`](../../../.github/ISSUE_TEMPLATE/ticket.md), in the template order. Delete the prose-rules comment and the guidance comments from the body. Use practical ASD-STE100 Simplified Technical English principles for prose.

- **Goal:** one or two sentences on the outcome and why it matters.
- **Context:** the facts about the current repository state that a reader needs to understand the work.
- **Scope:** what the work includes under **In scope** and what it excludes under **Out of scope**. Name the files or behavior when they are known.
- **Acceptance criteria:** a checklist of observable results. A reviewer can verify each item.
- **Decisions:** each decision in bold, followed by the reason for it.
- **Open questions:** optional. Each open question names who answers it and when. Delete the section when no questions are open.
- **Blocked by:** one `Blocked by #NN` line for each blocking issue, or `None`.

## Testing

Follow [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md) for mandatory test design, module boundaries, comments, and completion checks. Run these checks before opening a PR, and record them in the PR description:

```bash
uv run ruff format --check
uv run ruff check
uv run pytest
pnpm -C obsidian-plugin run build
```

Run the plugin build only when `obsidian-plugin/` changes. When a change affects how Word reads or saves a document, also check the generated fixtures in Word for Mac with `scripts/word_fixtures.py` and `scripts/word_check.applescript`.

## Push, PR, and Stacking

Use `stacc` for stacked branches and PRs. Run every command as `stacc <cmd> --no-interactive --json`, one command per call.

- Keep each branch scoped to one ticket. A ticket may span multiple sequential branches when that keeps reviews focused; apply the ticket continuity rule under **Tracker**.
- Split changes by building block when they can be reviewed and shipped independently: docx reading and patching, backends, CLI and core, and the Obsidian plugin. Combine them only when the change requires one coherent cross-boundary delivery.
- Keep later work from accumulating unrelated changes on an existing PR. Put independently reviewable work on its own branch and PR.
- Stack tickets in dependency order: the bottom branch is based on `main`, and each dependent ticket is based on its immediate parent.
- Submit stacks bottom to top. Each child PR targets its immediate parent.
- After a parent PR is squash merged, run `stacc sync` to restack child branches onto `main`.
- Create draft PRs while a ticket's acceptance criteria are incomplete.
- Never push, submit, merge, or change draft state without user authorization.

Immediately before creating a PR, require a clean working tree, run `git pull --ff-only origin main` on `main`, then run `stacc restack` so the stack is rooted on the current `origin/main`.

Typical commands:

```bash
stacc create jillian/<NN>-<short-desc> --no-interactive --json
stacc track --base <parent> --no-interactive --json
stacc restack --no-interactive --json
stacc submit --draft --title "<title>" --description @/tmp/pr-body.md --no-interactive --json
stacc log --no-interactive --json
stacc sync --no-interactive --json
```

## Quick Reference

| Concern  | Convention                                                                          |
| -------- | ----------------------------------------------------------------------------------- |
| Branch   | `jillian/<NN>-<short-desc>`                                                         |
| PR title | `<type>(<scope>): <description>`, scope required, no ticket prefix                  |
| PR body  | `.github/pull_request_template.md` sections only; durable prose                     |
| Issue    | `<scope>: <description>` title; `.github/ISSUE_TEMPLATE/ticket.md` sections only    |
| Commit   | Conventional commit, scope optional, inspect staged paths before committing         |
| Plans    | Local `.dev/plans/`, never committed                                                |
| Tracker  | GitHub Issues in `jekozyra/spsync`, via `gh`                                        |
| Testing  | ruff format, ruff check, pytest; plugin build and Word check when relevant          |
| Stack    | stacc; restack on current `origin/main` before PR creation; split by building block |
