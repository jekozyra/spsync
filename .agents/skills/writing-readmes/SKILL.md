---
name: writing-readmes
description: "Write, improve, or audit internal READMEs in this project. Use for root, app, and package READMEs, including README changes made as part of a feature. Ground setup in the repo, tailor sections to the reader, and apply the project's prose rules."
---

# Writing READMEs

A README is the project's entry point for project maintainers. Readers should learn what the project does, how to run or use it, and where to look next without first reading the source.

## How to write it

### 1. Read the repo first

Draft nothing until the repo tells you what is true. Gather:

- **Position:** Determine whether the README belongs to the monorepo root, an app, or a package. Read the workspace layout and any parent README.
- **Purpose and interface:** Read the relevant code, exports, and existing docs to identify the capability and its intended users. For a package, identify its public interface and runtime constraints.
- **Setup and usage:** Read the actual scripts, tool configuration, environment examples, and entry points. Use commands that exist; do not invent prerequisites or results.
- **Structure:** Identify the directories a reader needs to navigate and what each owns.
- **Existing content:** If a README exists, map its sections before editing it.

Completion criterion: the purpose, position, setup, usage, and relevant structure are supported by repository evidence, or their gaps are identified for step 2.

### 2. Ask only the gaps

Ask one question at a time about information the repo cannot establish, such as the intended purpose or a missing setup step. The audience is internal project maintainers. Do not ask the user to repeat facts already in the repo.

Completion criterion: every section in scope has enough information to write accurately.

### 3. Scope the sections

Choose sections for internal software engineers based on the README's position and the reader's task. Use reader-need `##` headings. Put feature- or subsystem-specific details beneath the relevant heading, using `###` only when it helps navigation.

| Section | When to include it | Content |
| --- | --- | --- |
| Title and one-liner | Always | Name and one sentence explaining what it does and for whom. |
| Overview | When the one-liner cannot explain essential concepts | Purpose, boundaries, and concepts needed for the primary task. |
| Setup | When the reader must prepare or run software | Prerequisites, ordered commands, working directories, and expected result. |
| Usage | When the reader can run or call a capability | A minimal example and essential caller decisions. |
| Configuration | When configuration affects setup or use | Environment variables, files, and required secrets, without secret values. |
| Project structure | At the root, or for non-obvious app or package layouts | Directories, responsibilities, and links to relevant READMEs. |
| API | For a library package | Supported exports, runtime constraints, and important effects or failure behavior. |
| Related docs | When deeper docs exist | Links to authoritative architecture, interface, and workflow documentation. |

- **Monorepo root:** Own the shared bootstrap, development commands, workspace map, and links to app and package READMEs. Leave their interface and configuration details in those READMEs.
- **App:** Own app-specific run and usage instructions, configuration, and integration boundaries. Link to the root for shared setup.
- **Package:** Own the public interface, runtime constraints, and minimal usage path. State where package-specific commands run. Link to the root for shared install and checks; omit the monorepo map.

Put maintainer-only build, release, or deployment instructions after the primary usage path when they belong in the README. Link to a runbook when the procedure is too long.

Completion criterion: each planned section has a distinct reader need and an evidence source.

### 4. Draft

Write the shortest README that lets a new internal engineer understand and use the relevant project, app, or package.

- Lead with a one-sentence description of what it is and who uses it. Put the primary reader task before maintainer-only flows.
- Use the reader-need headings above. Place feature details beneath the relevant heading.
- Give ordered, copy-pasteable setup commands for a fresh clone or the relevant workspace. State prerequisites and the expected result. Introduce commands with complete imperative sentences.
- Ensure commands are valid, achieve the intended goal, and are typo-free.
- Explain the public interface, runtime constraints, configuration, and error or no-op behavior when callers need that information. Link to deeper docs instead of repeating them.
- Map non-obvious directories to their responsibilities. Name the actual paths and domain concepts used by the repo.

Use these prose rules in every README:

- Write complete, well-formed sentences, including in terse chat modes. Keep sentences short and state one fact or instruction per sentence.
- Prefer active voice and explicit nouns over ambiguous pronouns. Use one consistent term for each concept.
- Avoid idioms and decorative language. Define an uncommon abbreviation before using it.
- Describe behavior precisely. Avoid vague praise such as "honest," "robust," "seamless," "powerful," "simply," "just," or "delightful."
- Start with the subject and action instead of filler such as "It's worth noting that," "In order to," or "This section covers."
- Give direct instructions when the answer is definite. Use "generally," "typically," or "you may want to" only for real uncertainty, and name that uncertainty.
- Use descriptive domain names instead of vague labels such as `data`, `manager`, `processor`, `utils`, or `helpers` when a precise name exists.
- Keep prose concise and complete. Do not use the em-dash character (U+2014); use a comma, colon, semicolon, or parentheses.

Completion criterion: a reader can follow the primary path from top to bottom, every claim is supported, and every sentence follows the prose rules.

### 5. Improve an existing README

Evaluate existing content against the sections above, not just its headings. For each section:

- Keep and tighten content that serves a reader need. Rename the heading when the catalog has a clearer name.
- Move necessary detail to the section where a reader expects it. Link to deeper docs for detail that would duplicate another source.
- Remove unsupported, stale, or unnecessary content. Fill missing setup, usage, interface, or navigation gaps.

Report which sections were kept, moved, added, or removed and why. Prefer a shorter result when the existing README repeats other docs, but do not cut information needed to run or use the project.

Completion criterion: every existing section has a disposition, and the resulting README covers every reader need in scope without duplication.

### 6. Verify

- Confirm setup and usage commands against the repo and their intended working directories. Run the relevant commands when feasible; report any that could not be verified by execution.
- Check that the primary reader task leads, maintainer-only flows follow, and headings match the section table.
- Check that internal links resolve and stated interfaces, constraints, and directory responsibilities are current.
- Recheck every sentence against the prose rules above, including the U+2014 restriction.

Completion criterion: the README is accurate, navigable, concise, and usable by an internal engineer without relying on unstated knowledge.
