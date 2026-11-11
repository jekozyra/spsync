# Coding standards

These standards apply to code, tests, fixtures, package structure, dependencies, comments, and repository documentation in this project.

## Toolchain

- Use Python 3.13 and uv for the command-line tool. Do not introduce Poetry, pip-tools, or a second Python environment manager.
- Use ruff for Python linting and formatting, `ty` for Python type checking, and `anti-slop-python` for the Python architectural rules. Do not add black, isort, flake8, pylint, or mypy.
- Use TypeScript, pnpm, and esbuild for the Obsidian plugin. The plugin tooling needs Node 23.6 or later, which runs `esbuild.ts` directly.
- Write scripts and tool configuration in TypeScript, such as `esbuild.ts` and `oxlint.config.ts`. Do not add `.mjs` files.
- Write relative TypeScript imports with the source file extension, such as `./settings.ts`.
- Use Oxlint, Oxfmt, and the vendored anti-slop rules for TypeScript. Do not add ESLint, Prettier, or Biome.
- Use lefthook for git hooks. Do not add the pre-commit framework or Husky.
- Declare each dependency that the code imports directly, even when another dependency already installs it.
- Use version ranges with a lower bound in `pyproject.toml` and `package.json`. The lockfiles, `uv.lock` and `pnpm-lock.yaml`, own the exact versions. Commit every lockfile change. Install with `uv sync --locked` and `pnpm install --frozen-lockfile`.
- Pin `oxlint` and `@oxlint/plugins` to the same exact version, so an upgrade moves both packages together.
- Use the repository scripts and `lefthook.yml` instead of adding parallel tool configurations.

## Repository responsibilities

The repository follows this structure:

```text
src/spsync/                         Command-line tool, sync core, docx transforms, and backends
obsidian-plugin/                    Obsidian plugin that runs the command-line tool
obsidian-plugin/tools/oxlint/       Vendored Oxlint rules
scripts/                            Word fixture generation and checks against Word for Mac
tests/                              pytest suite and .docx fixtures
```

- Keep sync behavior in the Python package. The plugin collects user intent, runs the command-line tool, and shows its results. The plugin does not parse or patch documents.
- Keep the command-line tool usable without the plugin.
- Keep `scripts/` for developer checks. Code in `src/spsync/` does not import from `scripts/`.
- Create a new module only when a coherent capability needs its own interface. Do not create placeholder modules.

## Change scope

- Keep branches and pull requests small, focused, and reviewable. Treat docx reading and patching, backends, the sync core and command-line tool, and the Obsidian plugin as separate building blocks.
- A ticket may produce multiple branches and pull requests. Prefer this split when the ticket crosses building blocks. Open one pull request per branch.
- Keep the work in one branch and pull request only when splitting would prevent the work from building, or when the entire change touches five files or fewer.

## Python source structure

The Python package uses this structure:

```text
src/spsync/
  cli.py         Command parsing and output; no sync logic
  config.py      SPSYNC_* environment variables and config.json
  core.py        Pull, push, sync, and create; three-way merge by paragraph
  store.py       Per-vault state under <vault>/.spsync: the pulled .docx and its block map
  mdparse.py     Obsidian note to blocks and comment callouts
  inline.py      Inline Markdown to Word run segments, and the reverse
  ooxml.py       OOXML helpers shared by the reader and the patcher
  reader/        .docx to blocks and Markdown: parts, paragraphs, comments, items
  patch/         Note edits applied onto the original .docx: patcher, runs, tables, comments, diff
  local.py       Backend protocols, the OneDrive-file backend, and the Router that picks a backend per item
  word/          Backend that drives the signed-in Word app: script, app, text, ops, planner, backend
  graph.py       Backend that calls Microsoft Graph
  auth.py        Microsoft identity sign-in and the token cache
```

Follow these rules for the Python source:

- Keep `cli.py` to argument parsing, configuration lookup, and output. Put behavior that the watcher or the plugin also needs in `core.py`.
- Keep the docx transforms (`reader/`, `inline.py`, `patch/`, and `ooxml.py`) free of network, file-system, and subprocess calls. They take bytes or parsed documents and return results.
- Every backend implements the `Backend` protocol in `local.py`. `core.py` depends on the `SessionBackend` protocol, not on a concrete backend.
- A package keeps the import path of the module that it replaced. Its `__init__.py` is the public interface and lists it in `__all__`.
- Split a module by responsibility when it grows past the `anti-slop-python` module-size limit. Turn the module into a package with the same import path when callers import it by name.

## Plugin source structure

```text
obsidian-plugin/
  main.ts                 Plugin entry point, commands, and settings tab
  esbuild.ts              Bundle script for main.js
  oxlint.config.ts        Oxlint configuration
  tools/oxlint/anti-slop/ Vendored Oxlint rules and their UPSTREAM.md
```

- Run the command-line tool through one function that builds its arguments and parses its JSON output. Commands and views call that function.
- Do not edit `main.js`. esbuild generates it, and `.gitignore` excludes it.

## Modules and responsibility

A module is a function, file, class, package, or larger slice with one interface and one implementation.

- Give each module one cohesive responsibility. Cohesion means that the module's decisions change for the same reason.
- Do not interpret single responsibility as one function per file or one package per concept.
- Prefer a deep module. A deep module provides substantial behavior through a small interface.
- Keep interfaces smaller than their implementations. Hide ordering, validation, and integration complexity when callers do not need that knowledge.
- Place a seam where behavior actually varies. Two adapters demonstrate a real seam. One adapter may not justify an abstraction.
- Avoid pass-through wrappers. Apply the deletion test: if deleting a module only removes forwarding code, the module is too shallow.
- Keep domain behavior local. Do not repeat the same rule in the command-line tool, the backends, the plugin, and tests.
- Accept dependencies instead of constructing infrastructure inside domain behavior.
- Return results when possible. Keep side effects in explicit adapters or host composition.
- Keep private implementation details private. Prefix them with `_` in Python, and do not export them from TypeScript. Do not expose a symbol only to make an internal test convenient.
- Define protocols, dataclasses, and type aliases before the functions that use them when practical.
- Define helper functions and private methods before their first use when practical.
- Do not create generic `utils` or `helpers` collections. Name a module after the capability or domain concept it owns.

## Document fidelity and data authority

The remote `.docx` is the authoritative document. The note and the block map are derived from it.

```text
remote .docx --pull--> <vault>/.spsync/<ref>.docx   pulled copy, base of the next merge
                  `--> block map                     paragraph identities and locks
                  `--> note.md                       derived; the user edits it

note.md + block map --push--> patched .docx --upload--> remote .docx
```

- Change only the paragraphs that the note changed. Keep unchanged paragraphs byte-for-byte identical, and keep the formatting of unchanged words.
- Do not rewrite locked content: tables, images, fields, content controls, footnotes, and paragraphs with pending tracked changes. Skip an edit to locked content with a warning.
- Never upload text inside `%% ... %%`.
- Surface overlapping edits as `[!conflict]` callouts. Do not resolve a conflict silently.
- Detect a remote change since the last pull before an upload. Do not overwrite a newer remote version.
- Preserve paragraph and comment identities across edits. Do not delete and recreate a paragraph or a comment when the operation means edit, move, or reply.
- Keep the note format stable. A change to callout syntax, frontmatter keys, or the block map format must read notes and state written by the previous version.
- Validate untrusted data where it enters the program: documents, notes, Graph responses, Word output, and configuration.

## Dependency direction and composition

```text
cli.py --> core.py --> SessionBackend protocol <-- Router (local.py) --> local, word/, graph.py
              |
              `--> mdparse.py, reader/, patch/ --> inline.py, ooxml.py

config.py <-- cli.py, auth.py, local.py
```

- Modules depend only in the direction of the illustration. A docx transform does not import `core.py`, `cli.py`, or a backend.
- Third-party types, such as python-docx objects, lxml elements, and Graph JSON, stay inside the module that uses them. Do not let them become the block model or the note format.
- The plugin depends on the command-line interface, not on Python internals.
- Use synthetic documents only. Do not commit documents, notes, or Graph responses from a real tenant.

## Configuration

- Read `SPSYNC_*` environment variables and `~/.config/spsync/` only in `config.py`. Other modules call its functions.
- List every environment variable in the README configuration table.
- Give each setting a documented default when the tool can work without it. Fail with a message that names the setting when it cannot.
- Store tokens in the macOS Keychain through msal-extensions. Use the private file cache only when the Keychain is unavailable, and warn the user when that happens. Do not write credentials or tokens to the vault, `.spsync/`, or a configuration file.

## Interfaces, state, and errors

- Make caller responsibilities and invariants explicit in types, names, and documentation.
- Annotate every function parameter and return type. Do not use `Any`, `list[Any]`, or `dict[str, Any]` to avoid naming a type. Prefer a `TypedDict` or a dataclass for JSON from Graph and Word that callers read by key.
- Prefer pure transformations for document and note data.
- Do not mutate caller-owned input unless the interface explicitly promises mutation.
- Represent expected failures with explicit result values or typed exceptions at the owning seam, such as `SyncError`, `GraphError`, or `ConflictError`. Catch a specific exception type. Do not catch `Exception` or use a bare `except`.
- Translate failures into user messages and exit codes in `cli.py`. Do not print or exit from a reusable module. Interactive sign-in prompts in `auth.py` are the only exception.
- Use direct attribute access for a known interface. Do not use `getattr`, `setattr`, or `delattr`.
- Keep sync, conflict, retry, and no-op states truthful. Do not report a push before the upload succeeds.

## Named values

A magic value is a literal whose meaning is not clear where it appears, or that must stay equal to the same value somewhere else. This rule applies to strings, numbers, booleans, regular expressions, and literal lists, tuples, dictionaries, and objects.

- Give a magic value a descriptive name. Do not repeat the literal.
- Include units in numeric names, such as `POLL_INTERVAL_SECONDS` or `MAX_SNIPPET_CHARS`, or use a named conversion factor.
- Use `UPPER_SNAKE_CASE` for a module-level constant that names a literal value. Use `snake_case` for Python functions and variables, and `camelCase` for TypeScript functions and variables.
- Build a message that states a policy value from the named value. Do not repeat the number in the message text.
- Define a closed set of values, such as backends, sync statuses, or block kinds, as an `Enum`, a `Literal` type, or a TypeScript `as const` array. Do not compare against bare literals.
- Use a keyword-only parameter in Python, or an options object in TypeScript, instead of a bare boolean argument when the meaning of `True` is not clear at the call site.

Put each named value at the narrowest scope that owns it:

| Scope                                         | Location                                                        |
| --------------------------------------------- | --------------------------------------------------------------- |
| Used in one module                            | A constant at the top of that module, after the imports         |
| Used in more than one module                  | An export from the module that owns the concept                 |
| Part of the note format or the block map      | An export from `mdparse.py`, `reader`, or `store.py`            |
| Varies between users, or is a credential      | A setting read by `config.py`, or the Keychain                  |

- Do not create a constants module for one value. A module that owns the value can export it instead.
- Do not put user settings, tenant identifiers, or credentials in a constant. Use configuration.

Keep these values inline:

- A value used once whose meaning is clear where it appears, such as a user-facing message or a log line.
- OOXML element and attribute names in an XPath expression or an lxml call, when the OOXML name already states the meaning.
- HTTP status codes, obvious indices, `0` and `1` as identity or step values, and protocol-defined markers when a name adds no meaning.
- Test fixtures, when the literal shows the expected behavior more clearly than a name would.

## Comments and illustrations

Add a comment when code cannot clearly express domain meaning, an architectural invariant, or a caller decision.

- Explain when to use an interface.
- Explain how similar interfaces differ.
- State which invariant the implementation preserves.
- State important no-op, failure, ordering, or ownership behavior.
- Do not narrate implementation steps that the code already makes clear.
- Use a module docstring to explain purpose, data flow, and invariants.
- Use a function docstring, or JSDoc in TypeScript, when a caller needs usage guidance, responsibilities, effects, or error behavior.
- Keep comments accurate when behavior changes. Remove stale or redundant comments.

Use practical ASD-STE100 Simplified Technical English principles:

- Use short sentences.
- State one fact or instruction per sentence.
- Prefer active voice.
- Use explicit nouns instead of ambiguous pronouns.
- Use one consistent term for each concept.
- Avoid idioms and decorative language.
- Define an uncommon abbreviation before using it.
- Use precise descriptions instead of "honest," "robust," "seamless," "powerful," "simply," "just," or "delightful." Start with the subject and action rather than "It's worth noting that," "In order to," or "This section covers."
- Give direct instructions when the answer is definite. Reserve "generally," "typically," and "you may want to" for real uncertainty, and name that uncertainty.

Illustrations are especially useful. Add a concise ASCII illustration near the top of a module when the illustration clarifies the block model, OOXML structure, merge inputs, or data ownership.

```text
w:body
  |-- w:p (block)  --block map id--> note paragraph
  |     `-- w:r (run) --> inline segment
  `-- w:tbl        locked; shown, never rewritten

word/comments.xml --w:id--> [!comment] callout under its paragraph
```

Use real OOXML and domain names in an illustration. Keep the illustration close to the code that it describes. Update the illustration when the relationships change.

- A `typing.cast` call, a `# type: ignore` comment, or a TypeScript `as` assertion requires a `SAFETY:` comment that states why the value has that type. The anti-slop Oxlint rules enforce this for TypeScript.

## Tests

- Add tests that protect distinct behavior or a regression.
- Prefer round-trip tests through the public pull, push, and sync interface to tests of one internal function.
- Do not duplicate test coverage. If a round-trip test covers the case, do not add a narrower test.
- Add a narrow test when it covers a distinct case more precisely or efficiently, such as one OOXML construct.
- Add a narrow test for foundational behavior that must be correct, such as inline Markdown parsing.
- Test through the same public interface that callers use.
- Test invariants, error modes, no-op behavior, and identity preservation when those behaviors are part of the interface.
- A change to `reader/`, `inline.py`, `patch/`, or `word/` requires a round-trip test that proves unchanged content stays unchanged.
- Keep fixtures small and explicit. Use synthetic documents only. Add a `.docx` fixture saved by Word only when a generated document cannot reproduce the case, and name the Word version in the test.
- Do not make private implementation details public only for tests.
- Name test files `tests/test_<module>.py`, or name a file for a behavior across modules after that behavior, such as `tests/test_roundtrip.py`.
- Replace a backend with a fake that implements the `Backend` protocol and is passed to the code under test. Do not use `unittest.mock.patch` or monkeypatching to replace a dependency.
- Mark a test that needs Word for Mac, the OneDrive app, or a Microsoft tenant with `@pytest.mark.integration`. `uv run pytest` skips integration tests.

## Formatting and repository prose

- The lefthook pre-commit hook runs the formatters, linters, type checkers, and unit tests. Do not bypass it.
- Run `uv run ruff format` and `pnpm -C obsidian-plugin run format` before committing a changed supported file.
- Do not use the em-dash character, codepoint U+2014, in repository content. Use punctuation such as a comma, colon, semicolon, or parentheses.
- Do not use curly quotation marks or apostrophes, codepoints U+2018, U+2019, U+201C, and U+201D. Use straight quotation marks (") and apostrophes ('). This rule includes user-facing messages. It does not apply to test fixtures that reproduce Word output.
- Keep the upstream text of a vendored agent skill or a vendored tool, such as `.agents/skills/writing-readmes/` or `obsidian-plugin/tools/oxlint/anti-slop/`. A vendored item names its source in its front matter or in `UPSTREAM.md`. The prose rules in this document do not apply to vendored content. Change vendored content only by installing a new version from its source, and record each local deviation in `UPSTREAM.md`.
- Use descriptive domain names. Avoid vague names such as `data`, `manager`, `processor`, `utils`, or `helpers` when a precise name exists.
- Keep public prose concise and complete.

## Completion checklist

Before declaring a code change complete:

1. Confirm that the change belongs in the selected module or in the plugin.
2. Confirm that dependency direction still follows the illustration in [Dependency direction and composition](#dependency-direction-and-composition).
3. Confirm that the document fidelity rules still hold.
4. Confirm that each new interface is necessary and smaller than the behavior behind it.
5. Confirm that comments explain meaning or decisions instead of narrating code.
6. Confirm that tests protect distinct interface behavior.
7. Confirm that defined acceptance criteria are met.
8. Run `uv run ruff format --check`, `uv run ruff check`, `uv run ty check`, `uv run anti-slop-python src tests`, and `uv run pytest`.
9. When `obsidian-plugin/` changes, run its `format:check`, `lint`, and `build` scripts.
10. When the change affects how Word reads or saves a document, generate the fixtures with `scripts/word_fixtures.py` and check them in Word for Mac with `scripts/word_check.applescript`.
