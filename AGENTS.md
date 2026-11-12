# AGENTS.md

spsync edits and comments on SharePoint Word documents as Obsidian notes. It is a Python 3.13 command-line tool built with uv, plus a TypeScript Obsidian plugin in `obsidian-plugin/` that runs the command-line tool.

## Mandatory coding standards

Before changing code, tests, fixtures, package structure, dependencies, comments, or repository documentation, read and follow [`CODING_STANDARDS.md`](CODING_STANDARDS.md). These standards are mandatory. They define repository structure, module design, document fidelity, comments, testing, language, and formatting.

## README documentation

Before creating, rewriting, improving, or auditing the README, read and follow [`.agents/skills/writing-readmes/SKILL.md`](.agents/skills/writing-readmes/SKILL.md). Use its internal-audience structure and prose rules for README changes made as part of other work, too.

## Commands

```sh
uv sync --locked
uv run lefthook install
uv run ruff format
uv run ruff check
uv run ty check
uv run anti-slop-python src tests
uv run pytest
pnpm -C obsidian-plugin install --frozen-lockfile
pnpm -C obsidian-plugin run format
pnpm -C obsidian-plugin run lint
pnpm -C obsidian-plugin run test
pnpm -C obsidian-plugin run build
```

## Structure

- `src/spsync/`: the command-line tool, its sync core, docx reading and patching, and the local, word, and graph backends
- `obsidian-plugin/`: the Obsidian plugin, which runs the command-line tool
- `obsidian-plugin/tools/oxlint/anti-slop/`: vendored Oxlint rules
- `scripts/`: Word fixture generation and AppleScript checks against Word for Mac
- `scripts/guide_images/`: the renderer for the animations in `docs/guide.md`
- `tests/`: the pytest suite and `.docx` fixtures

## Workflow

Follow [`.agents/skills/b-spsync-workflow/SKILL.md`](.agents/skills/b-spsync-workflow/SKILL.md) for branch names, conventional commits, local-only plans, issue and PR titles and bodies, and stacc stacking conventions. It overrides general workflow defaults in this repo.

### Issue tracker

This project's tracker is **GitHub Issues** in `jekozyra/spsync`, operated through the `gh` CLI. Tracker-specific operations for the bindle planning skills live in [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md), under its "Wayfinding operations" section. Skills resolve the tracker through this pointer; with no tracker configured they fall back to the local-markdown tracker. Keep plans and other local working notes in the gitignored `.dev/` directory.

### Writing and output style

- Follow `CODING_STANDARDS.md` for repository prose. Never use the em-dash character, codepoint U+2014, in chat or messages to people.
- Keep output concise, with no filler or preamble. Human-facing documents, PR descriptions, and messages to people always get full, well-formed prose.

### Clarify requirements before acting

Before any non-trivial task, interview the user to remove ambiguity, one question at a time. Cover goals, scope, constraints, preferences, edge cases, and definition of done; skip anything already clear. Use the harness's structured question tool when one is available. Summarize the plan and get confirmation before doing the work. Skip the interview only for trivial requests or when told to proceed.

### Web search and external facts

For current or external facts, such as library and API documentation, version-specific behavior, or prior art, use the harness's web tools rather than recall. Run broad research inside a sub-agent and return only distilled findings. Prefer official or primary sources, and note the access date for time-sensitive facts.

### Agent instruction files

`AGENTS.md` is the single source of project agent instructions. Where a harness only auto-loads its own file, such as `CLAUDE.md`, add a one-line bridge that imports `@AGENTS.md` rather than duplicating content.

### Git hygiene

- Do not commit code directly to `main`; branch first and submit through a PR.
- Prefer new commits over amending. Force-push only with `--force-with-lease`.
- Confirm before destructive git operations.
- Keep commands auto-allowable: one simple command per call. Pass paths as arguments (`git -C <path> <sub>`, `rg <pat> <path>`, `pnpm -C <path> <script>`) rather than chaining with `cd`. Run destructive git operations (`push --force`, `reset --hard`, `clean`, `branch -D`) in plain form so the safety prompt fires.
- Do not bypass the lefthook pre-commit hook with `--no-verify`. Fix the reported findings instead.
