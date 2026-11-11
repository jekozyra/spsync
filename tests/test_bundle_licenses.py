"""Tests for scripts/bundle_licenses.py, which writes the notices into the standalone build."""

import subprocess
import sys
from importlib import metadata
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bundle_licenses.py"


def bundle(dest: Path, requirements: str) -> subprocess.CompletedProcess[str]:
    req = dest / "requirements.txt"
    req.write_text(requirements)
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(dest), str(req)], capture_output=True, text=True, check=False
    )


def test_gpl_package_gets_its_license_and_a_written_offer(tmp_path: Path) -> None:
    merge3 = metadata.version("merge3")
    httpx = metadata.version("httpx")
    result = bundle(tmp_path, f"httpx=={httpx}\nmerge3=={merge3}\nabsent-package==1.0 ; sys_platform == 'win32'\n")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "licenses" / f"merge3-{merge3}" / "COPYING").is_file()
    assert (tmp_path / "licenses" / f"httpx-{httpx}" / "LICENSE.md").is_file()
    notices = (tmp_path / "THIRD_PARTY_NOTICES.md").read_text()
    assert f"| merge3 | {merge3} | GPL-2.0-or-later |" in notices
    assert "## Written offer for source code" in notices
    assert f"https://github.com/jekozyra/spsync/tree/v{metadata.version('spsync')}" in notices
    assert "absent-package" not in notices
    assert "| Python |" in notices


def test_permissive_packages_get_no_written_offer(tmp_path: Path) -> None:
    result = bundle(tmp_path, f"httpx=={metadata.version('httpx')}\n")
    assert result.returncode == 0, result.stderr
    assert "Written offer" not in (tmp_path / "THIRD_PARTY_NOTICES.md").read_text()
