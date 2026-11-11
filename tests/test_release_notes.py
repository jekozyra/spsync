"""Tests for scripts/release_notes.py, which reads the release notes from CHANGELOG.md."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release_notes.py"

CHANGELOG = """# Changelog

## [Unreleased]

- Work in progress.

## [1.2.0] - 2026-11-12

### Added

- A new command.

## [1.1.0] - 2026-10-01

### Fixed

- An old bug.

## [1.0.0] - 2026-09-01

[1.2.0]: https://github.com/jekozyra/spsync/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jekozyra/spsync/releases/tag/v1.1.0
"""


def notes(tmp_path: Path, version: str) -> subprocess.CompletedProcess[str]:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, "--changelog", str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_prints_only_the_section_of_the_version(tmp_path: Path) -> None:
    result = notes(tmp_path, "1.2.0")
    assert result.returncode == 0
    assert result.stdout == "### Added\n\n- A new command.\n"


def test_last_section_stops_at_the_link_definitions(tmp_path: Path) -> None:
    result = notes(tmp_path, "1.1.0")
    assert result.stdout == "### Fixed\n\n- An old bug.\n"


def test_missing_or_empty_section_fails(tmp_path: Path) -> None:
    for version in ("9.9.9", "1.0.0", "1.2"):
        result = notes(tmp_path, version)
        assert result.returncode == 1, version
        assert f"no notes for version {version}" in result.stderr
