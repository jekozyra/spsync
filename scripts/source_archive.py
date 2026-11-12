"""Write the source archive that each release publishes next to the standalone CLI.

The standalone build bundles merge3, which is licensed under GPL-2.0-or-later. GPLv2 section 3(a) lets
a binary ship together with its complete corresponding source code, so no written offer is necessary.
The release workflow attaches this archive to every release. THIRD_PARTY_NOTICES.md in the CLI archive
names this archive.

```text
spsync-<version>-source.tar.gz
  spsync-<version>-source/
    spsync/            git archive of HEAD: the CLI, the plugin, uv.lock, and the build scripts
    packages/<sdist>   the source distribution of each bundled package, at its uv.lock version
```

uv.lock gives the URL and the SHA-256 hash of each source distribution. The script exits with 1 when a
package has no source distribution in uv.lock, or when a download fails or does not match its hash.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT = "spsync"
HASH_PREFIX = "sha256:"
PACKAGES_FOLDER = "packages"
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s;]+)")
EXIT_INCOMPLETE_SOURCE = 1


class SourceError(Exception):
    """A source distribution is missing from uv.lock, or its download failed or has the wrong hash."""


@dataclass(frozen=True)
class SourceDistribution:
    """One source distribution from uv.lock."""

    url: str
    sha256: str

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


def source_archive_name(version: str) -> str:
    """The file name of the source archive for one spsync version."""
    return f"{PROJECT}-{version}-source.tar.gz"


def read_requirements(text: str) -> list[tuple[str, str]]:
    """The (name, version) pairs in the output of `uv export --no-hashes`. Markers are ignored."""
    return [(m["name"], m["version"]) for line in text.splitlines() if (m := REQUIREMENT.match(line.strip()))]


def _locked_sdists(lock_text: str, requirements: list[tuple[str, str]]) -> list[SourceDistribution]:
    locked = {(p.get("name"), p.get("version")): p for p in tomllib.loads(lock_text).get("package", [])}
    sdists = []
    for name, version in requirements:
        sdist = locked.get((name, version), {}).get("sdist")
        if not sdist or not str(sdist.get("hash", "")).startswith(HASH_PREFIX):
            raise SourceError(f"uv.lock has no source distribution with a SHA-256 hash for {name} {version}.")
        sdists.append(SourceDistribution(sdist["url"], sdist["hash"].removeprefix(HASH_PREFIX)))
    return sdists


def _download(sdist: SourceDistribution) -> bytes:
    try:
        with urllib.request.urlopen(sdist.url) as response:
            content = response.read()
    except urllib.error.URLError as exc:
        raise SourceError(f"{sdist.url}: {exc.reason}") from exc
    if hashlib.sha256(content).hexdigest() != sdist.sha256:
        raise SourceError(f"{sdist.filename} does not match its SHA-256 hash in uv.lock.")
    return content


def _write_archive(path: Path, root: str, project_tar: bytes, packages: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive, tarfile.open(fileobj=io.BytesIO(project_tar)) as project:
        for member in project.getmembers():
            content = project.extractfile(member) if member.isfile() else None
            member.name = f"{root}/{PROJECT}/{member.name}"
            archive.addfile(member, content)
        for filename, content in packages:
            info = tarfile.TarInfo(f"{root}/{PACKAGES_FOLDER}/{filename}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the source archive of a spsync release.")
    parser.add_argument("requirements", type=Path, help="The output of uv export --no-dev --no-emit-project")
    parser.add_argument("--repo", type=Path, default=REPO, help="The repository root; HEAD is archived")
    parser.add_argument("--output-dir", type=Path, default=REPO / "dist", help="The folder for the archive")
    args = parser.parse_args()
    version = tomllib.loads((args.repo / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    try:
        requirements = read_requirements(args.requirements.read_text(encoding="utf-8"))
        sdists = _locked_sdists((args.repo / "uv.lock").read_text(encoding="utf-8"), requirements)
        packages = [(sdist.filename, _download(sdist)) for sdist in sdists]
    except SourceError as exc:
        print(f"source_archive.py: {exc}", file=sys.stderr)
        return EXIT_INCOMPLETE_SOURCE
    project_tar = subprocess.run(
        ["git", "-C", str(args.repo), "archive", "--format=tar", "HEAD"], capture_output=True, check=True
    ).stdout
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / source_archive_name(version)
    _write_archive(path, f"{PROJECT}-{version}-source", project_tar, packages)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
