"""Tests for scripts/source_archive.py, which writes the source archive of each release."""

import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "source_archive.py"
SDIST = b"demo source distribution"
# A git hook sets GIT_DIR and GIT_INDEX_FILE. Without this filter, git commands in the temporary
# repository change the repository that runs the hook.
CLEAN_ENV = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def make_repo(root: Path, sdist_hash: str) -> Path:
    repo = root / "repo"
    repo.mkdir()
    sdist = root / "demo-1.0.tar.gz"
    sdist.write_bytes(SDIST)
    (repo / "pyproject.toml").write_text('[project]\nname = "spsync"\nversion = "1.2.3"\n')
    (repo / "uv.lock").write_text(
        f'[[package]]\nname = "demo"\nversion = "1.0"\nsdist = {{ url = "{sdist.as_uri()}", hash = "{sdist_hash}" }}\n'
    )
    git = ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com"]
    subprocess.run([*git, "init", "--quiet"], check=True, env=CLEAN_ENV)
    subprocess.run([*git, "add", "."], check=True, env=CLEAN_ENV)
    subprocess.run([*git, "commit", "--quiet", "-m", "init"], check=True, env=CLEAN_ENV)
    return repo


def archive(root: Path, repo: Path, requirements: str) -> subprocess.CompletedProcess[str]:
    req = root / "requirements.txt"
    req.write_text(requirements)
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(req), "--repo", str(repo), "--output-dir", str(root / "dist")],
        capture_output=True,
        text=True,
        check=False,
        env=CLEAN_ENV,
    )


def test_archive_holds_the_project_and_each_sdist(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, f"sha256:{hashlib.sha256(SDIST).hexdigest()}")
    result = archive(tmp_path, repo, "demo==1.0 ; sys_platform == 'darwin'\n")
    assert result.returncode == 0, result.stderr
    with tarfile.open(tmp_path / "dist" / "spsync-1.2.3-source.tar.gz") as tar:
        assert "spsync-1.2.3-source/spsync/pyproject.toml" in tar.getnames()
        sdist = tar.extractfile("spsync-1.2.3-source/packages/demo-1.0.tar.gz")
        assert sdist is not None and sdist.read() == SDIST


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, f"sha256:{'0' * 64}")
    result = archive(tmp_path, repo, "demo==1.0\n")
    assert result.returncode == 1
    assert "demo-1.0.tar.gz does not match its SHA-256 hash" in result.stderr
    assert not (tmp_path / "dist" / "spsync-1.2.3-source.tar.gz").exists()


def test_package_without_a_locked_sdist_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, f"sha256:{hashlib.sha256(SDIST).hexdigest()}")
    result = archive(tmp_path, repo, "other==2.0\n")
    assert result.returncode == 1
    assert "no source distribution with a SHA-256 hash for other 2.0" in result.stderr
