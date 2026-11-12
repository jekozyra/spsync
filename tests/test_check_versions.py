"""Tests for scripts/check_versions.py, which the pre-commit hook and the release workflow run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_versions.py"


def write_manifests(root: Path, pyproject: str, manifest: str, package: str) -> None:
    (root / "obsidian-plugin").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nname = "spsync"\nversion = "{pyproject}"\n')
    (root / "obsidian-plugin" / "manifest.json").write_text(json.dumps({"id": "spsync", "version": manifest}))
    (root / "obsidian-plugin" / "package.json").write_text(json.dumps({"name": "spsync", "version": package}))


def check(root: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *options], capture_output=True, text=True, check=False
    )


def test_matching_versions_pass(tmp_path: Path) -> None:
    write_manifests(tmp_path, "1.2.3", "1.2.3", "1.2.3")
    result = check(tmp_path)
    assert result.returncode == 0
    assert result.stdout == "spsync version 1.2.3\n"


@pytest.mark.parametrize(
    "versions", [("1.2.4", "1.2.3", "1.2.3"), ("1.2.3", "1.2.4", "1.2.3"), ("1.2.3", "1.2.3", "1.2.4")]
)
def test_a_different_version_in_any_manifest_fails(tmp_path: Path, versions: tuple[str, str, str]) -> None:
    write_manifests(tmp_path, *versions)
    result = check(tmp_path)
    assert result.returncode == 1
    assert "1.2.4" in result.stderr


def test_a_missing_version_fails(tmp_path: Path) -> None:
    write_manifests(tmp_path, "1.2.3", "1.2.3", "1.2.3")
    (tmp_path / "obsidian-plugin" / "package.json").write_text(json.dumps({"name": "spsync"}))
    result = check(tmp_path)
    assert result.returncode == 1
    assert "obsidian-plugin/package.json: missing" in result.stderr


def test_expect_fails_when_the_tag_version_differs(tmp_path: Path) -> None:
    write_manifests(tmp_path, "1.2.3", "1.2.3", "1.2.3")
    assert check(tmp_path, "--expect", "1.2.3").returncode == 0
    result = check(tmp_path, "--expect", "1.3.0")
    assert result.returncode == 1
    assert "every manifest must declare version 1.3.0" in result.stderr
