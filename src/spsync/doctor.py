"""First-run setup checks for `spsync doctor`.

Each check reports pass or fail. A failed check names one fix in plain language. A failed required
check means that a pull or a push will fail. The checks only report; they never change a setting.

```text
SetupEnvironment --run_checks--> [Check]
  cloud_storage        OneDrive folder   required in local mode
  applications         Word for Mac      required
  automation_allowed   Automation        required; starts Word hidden when Word is closed
  author               author name       always passes; shows the value and how to change it
```
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from . import config
from .local import CLOUD_STORAGE, LOCAL, AuthorSource, comment_author, onedrive_folders
from .word import WordError, automation_allowed

PACKAGE_NAME = "spsync"
WORD_APP_NAME = "Microsoft Word.app"
APPLICATION_FOLDERS = (Path("/Applications"), Path.home() / "Applications")
AUTHOR_SOURCES: dict[AuthorSource, str] = {
    "setting": "the spsync author setting",
    "full_name": "your macOS full name",
    "login_name": "your macOS login name",
}


@dataclass(frozen=True)
class Check:
    """The result of one setup check. `fix` is empty when the check passes."""

    name: str
    ok: bool
    required: bool
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class SetupEnvironment:
    """The parts of the Mac that the checks read. Tests pass temporary folders and a fake Word probe."""

    cloud_storage: Path
    applications: tuple[Path, ...]
    backend: str
    author: str
    author_source: AuthorSource
    automation_allowed: Callable[[], bool]

    @classmethod
    def from_system(cls) -> SetupEnvironment:
        author, source = comment_author()
        return cls(
            cloud_storage=CLOUD_STORAGE,
            applications=APPLICATION_FOLDERS,
            backend=config.backend_mode() or LOCAL,
            author=author,
            author_source=source,
            automation_allowed=automation_allowed,
        )


def _version() -> Check:
    try:
        version = metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        version = "unknown"
    return Check("CLI version", ok=True, required=False, detail=f"{PACKAGE_NAME} {version}")


def _onedrive(env: SetupEnvironment) -> Check:
    name = "OneDrive folder"
    required = env.backend == LOCAL
    folders = onedrive_folders(env.cloud_storage)
    if folders:
        return Check(name, ok=True, required=required, detail=", ".join(str(f) for f in folders))
    return Check(
        name,
        ok=False,
        required=required,
        detail=f"No OneDrive folder in {env.cloud_storage}.",
        fix="Install the OneDrive app, sign in with your work account, and let OneDrive sync files to this Mac.",
    )


def _word_app(env: SetupEnvironment) -> Path | None:
    for folder in env.applications:
        app = folder / WORD_APP_NAME
        if app.exists():
            return app
    return None


def _word(app: Path | None) -> Check:
    name = "Word for Mac"
    if app:
        return Check(name, ok=True, required=True, detail=str(app))
    return Check(
        name,
        ok=False,
        required=True,
        detail="Microsoft Word is not in the Applications folder.",
        fix="Install Microsoft Word for Mac and sign in with your work account.",
    )


def _automation(env: SetupEnvironment, app: Path | None) -> Check:
    name = "Automation permission"
    if app is None:
        return Check(
            name,
            ok=False,
            required=True,
            detail="Not checked, because Word is not installed.",
            fix="Install Word, then run spsync doctor again.",
        )
    try:
        allowed = env.automation_allowed()
    except WordError as exc:
        return Check(
            name,
            ok=False,
            required=True,
            detail=f"Word did not answer: {exc.message}",
            fix="Open Word, sign in, close any open dialog boxes, and run spsync doctor again.",
        )
    if allowed:
        return Check(name, ok=True, required=True, detail="spsync can control Word.")
    return Check(
        name,
        ok=False,
        required=True,
        detail="macOS does not let spsync control Word.",
        fix=(
            "Open System Settings > Privacy & Security > Automation. Under the app that runs spsync,"
            " such as Obsidian or Terminal, turn on Microsoft Word."
        ),
    )


def _author(env: SetupEnvironment) -> Check:
    return Check(
        "Author name",
        ok=True,
        required=False,
        detail=(
            f"{env.author}, from {AUTHOR_SOURCES[env.author_source]}."
            ' Change it with spsync mode --author "Your Name", or with the "Author name" setting of the Obsidian plugin.'
        ),
    )


def run_checks(env: SetupEnvironment) -> list[Check]:
    """Run every setup check in display order. The Automation check can start Word; see SetupEnvironment."""
    app = _word_app(env)
    return [_version(), _onedrive(env), _word(app), _automation(env, app), _author(env)]


def complete(checks: list[Check]) -> bool:
    """Whether every required check passed."""
    return all(c.ok or not c.required for c in checks)
