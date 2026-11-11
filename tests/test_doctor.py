from collections.abc import Callable
from pathlib import Path

import pytest

from spsync.doctor import Check, SetupEnvironment, complete, run_checks
from spsync.local import AuthorSource
from spsync.word import WordError, automation_allowed


class FakeWord:
    """A Word Automation probe that returns a fixed answer, or raises one error, and counts its calls."""

    def __init__(self, answer: bool | WordError = True) -> None:
        self.answer = answer
        self.calls = 0

    def automation_allowed(self) -> bool:
        self.calls += 1
        if isinstance(self.answer, WordError):
            raise self.answer
        return self.answer


MakeEnv = Callable[..., SetupEnvironment]


@pytest.fixture
def make_env(tmp_path: Path) -> MakeEnv:
    """A Mac with OneDrive and Word installed; keyword arguments remove or replace each part."""

    def make(
        *,
        onedrive: bool = True,
        word_app: bool = True,
        word: FakeWord | None = None,
        backend: str = "local",
        author: tuple[str, AuthorSource] = ("Ada Lovelace", "full_name"),
    ) -> SetupEnvironment:
        cloud = tmp_path / "CloudStorage"
        cloud.mkdir(exist_ok=True)
        if onedrive:
            (cloud / "OneDrive-Contoso").mkdir(exist_ok=True)
        apps = tmp_path / "Applications"
        apps.mkdir(exist_ok=True)
        if word_app:
            (apps / "Microsoft Word.app").mkdir(exist_ok=True)
        return SetupEnvironment(
            cloud_storage=cloud,
            applications=(tmp_path / "missing", apps),
            backend=backend,
            author=author[0],
            author_source=author[1],
            automation_allowed=(word or FakeWord()).automation_allowed,
        )

    return make


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


def test_ready_mac_passes_every_check(make_env: MakeEnv) -> None:
    checks = run_checks(make_env())
    assert [c.name for c in checks] == [
        "CLI version",
        "OneDrive folder",
        "Word for Mac",
        "Automation permission",
        "Author name",
    ]
    assert all(c.ok and not c.fix for c in checks)
    assert by_name(checks)["CLI version"].detail.startswith("spsync ")
    assert by_name(checks)["OneDrive folder"].detail.endswith("OneDrive-Contoso")
    assert complete(checks)


def test_missing_onedrive_fails_in_local_mode(make_env: MakeEnv) -> None:
    checks = run_checks(make_env(onedrive=False))
    onedrive = by_name(checks)["OneDrive folder"]
    assert not onedrive.ok
    assert onedrive.required
    assert "OneDrive app" in onedrive.fix
    assert not complete(checks)


def test_missing_onedrive_is_optional_in_graph_mode(make_env: MakeEnv) -> None:
    checks = run_checks(make_env(onedrive=False, backend="graph"))
    onedrive = by_name(checks)["OneDrive folder"]
    assert not onedrive.ok
    assert not onedrive.required
    assert complete(checks)


def test_missing_word_fails_and_skips_the_automation_probe(make_env: MakeEnv) -> None:
    word = FakeWord()
    checks = by_name(run_checks(make_env(word_app=False, word=word)))
    assert not checks["Word for Mac"].ok
    assert "Install Microsoft Word" in checks["Word for Mac"].fix
    assert not checks["Automation permission"].ok
    assert "Install Word" in checks["Automation permission"].fix
    assert word.calls == 0


def test_denied_automation_fails_with_the_settings_path(make_env: MakeEnv) -> None:
    checks = run_checks(make_env(word=FakeWord(answer=False)))
    automation = by_name(checks)["Automation permission"]
    assert not automation.ok
    assert "Privacy & Security > Automation" in automation.fix
    assert not complete(checks)


def test_word_error_fails_the_automation_check(make_env: MakeEnv) -> None:
    word = FakeWord(answer=WordError("Word did not start."))
    automation = by_name(run_checks(make_env(word=word)))["Automation permission"]
    assert not automation.ok
    assert "Word did not start." in automation.detail
    assert "Open Word" in automation.fix


@pytest.mark.parametrize(
    ("source", "phrase"),
    [
        ("setting", "the spsync author setting"),
        ("full_name", "your macOS full name"),
        ("login_name", "your macOS login name"),
    ],
)
def test_author_shows_value_source_and_how_to_change_it(make_env: MakeEnv, source: AuthorSource, phrase: str) -> None:
    author = by_name(run_checks(make_env(author=("ada", source))))["Author name"]
    assert author.ok
    assert not author.required
    assert author.detail.startswith(f"ada, from {phrase}.")
    assert "spsync mode --author" in author.detail


@pytest.mark.integration
def test_word_answers_the_automation_probe() -> None:
    assert automation_allowed()
