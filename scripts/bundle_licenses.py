"""Write the license notices for the packages that the standalone build bundles.

```text
uv export --no-dev --no-emit-project  --> requirements file: name==version ; marker
build environment importlib.metadata  --> license expression and license files of each package
                                            |
<dest>/THIRD_PARTY_NOTICES.md  <------------'  one row per package, source links, written offer
<dest>/licenses/<name>-<version>/<file>        the license files from each .dist-info folder
<dest>/licenses/python-<version>/LICENSE.txt   the CPython license; Nuitka bundles the standard library
```

Run the script with the Python of the build environment, so that importlib.metadata reads the bundled
packages. The script skips a requirement whose package is not installed, because its environment marker
excludes it on this Mac. The script exits with 1 when a bundled package has no license file, so a build
never ships without a notice. A package under a GPL license adds the written offer for source code that
the GPL requires for a binary distribution.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PROJECT = "spsync"
NOTICES_FILE = "THIRD_PARTY_NOTICES.md"
LICENSES_FOLDER = "licenses"
LICENSE_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")
COPYLEFT_MARKER = "GPL"
MAX_LICENSE_FIELD_CHARS = 40
REPOSITORY_URL_LABEL = "Repository, "
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s;]+)")
EXIT_INCOMPLETE_NOTICES = 1


@dataclass(frozen=True)
class BundledPackage:
    """One installed package that the standalone build includes, and its copied license files."""

    name: str
    version: str
    license: str
    license_folder: str


def _license_name(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression
    field = dist.metadata.get("License") or ""
    if field and "\n" not in field and len(field) <= MAX_LICENSE_FIELD_CHARS:
        return field
    return "see the license files"


def _license_files(dist: metadata.Distribution) -> list[Path]:
    files = []
    for path in dist.files or []:
        in_dist_info = path.parts[0].endswith(".dist-info")
        is_license = LICENSES_FOLDER in path.parts[1:-1] or path.name.upper().startswith(LICENSE_FILE_PREFIXES)
        if in_dist_info and is_license:
            files.append(Path(str(path.locate())))
    return files


def _copy_licenses(name: str, files: list[Path], dest: Path) -> str:
    folder = Path(LICENSES_FOLDER) / name
    (dest / folder).mkdir(parents=True, exist_ok=True)
    for file in files:
        shutil.copyfile(file, dest / folder / file.name)
    return folder.as_posix()


def _requirements(text: str) -> list[tuple[str, str]]:
    return [(m["name"], m["version"]) for line in text.splitlines() if (m := REQUIREMENT.match(line.strip()))]


def _python_license(dest: Path) -> BundledPackage:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    stdlib = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    folder = _copy_licenses(f"python-{version}", [stdlib / "LICENSE.txt"], dest)
    return BundledPackage("Python", version, "PSF-2.0", folder)


def _notices(packages: list[BundledPackage], source_url: str, contact: str) -> str:
    version = metadata.version(PROJECT)
    lines = [
        "# Third-party notices",
        "",
        f"The standalone {PROJECT} {version} build includes the packages below. Each package keeps its own",
        f"license. The license files are in the `{LICENSES_FOLDER}/` folder. {PROJECT} itself is licensed under",
        "the MIT license; see `LICENSE`.",
        "",
        "| Package | Version | License | License files | Source |",
        "|---|---|---|---|---|",
    ]
    for p in packages:
        source = (
            "https://www.python.org/downloads/source/"
            if p.name == "Python"
            else (f"https://pypi.org/project/{p.name}/{p.version}/#files")
        )
        lines.append(f"| {p.name} | {p.version} | {p.license} | `{p.license_folder}/` | {source} |")
    copyleft = [p for p in packages if COPYLEFT_MARKER in p.license]
    if copyleft:
        names = ", ".join(f"{p.name} {p.version} ({p.license})" for p in copyleft)
        lines += [
            "",
            "## Written offer for source code",
            "",
            f"This build includes {names}. For at least three years after the release of {PROJECT} {version},",
            f"the {PROJECT} maintainer gives any third party a complete machine-readable copy of the",
            "corresponding source code for this build, for a charge no more than the cost of the delivery.",
            f"Send the request to {contact}.",
            "",
            "The corresponding source code is also available now:",
            "",
            f"- {PROJECT} {version}: {source_url}. Its `uv.lock` file pins the version of each package.",
            "- Each package: the PyPI link in the Source column of the table above.",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the license notices for the standalone spsync build.")
    parser.add_argument("dest", type=Path, help="The folder of the standalone build")
    parser.add_argument("requirements", type=Path, help="The output of uv export --no-dev --no-emit-project")
    args = parser.parse_args()
    project = metadata.metadata(PROJECT)
    urls = [u for u in project.get_all("Project-URL") or [] if u.startswith(REPOSITORY_URL_LABEL)]
    if not urls:
        print(f"bundle_licenses.py: pyproject.toml has no {REPOSITORY_URL_LABEL.rstrip(', ')} URL.", file=sys.stderr)
        return EXIT_INCOMPLETE_NOTICES
    source_url = f"{urls[0].removeprefix(REPOSITORY_URL_LABEL)}/tree/v{project['Version']}"
    packages = []
    for name, version in _requirements(args.requirements.read_text(encoding="utf-8")):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        files = _license_files(dist)
        if not files:
            print(f"bundle_licenses.py: {name} {version} has no license file.", file=sys.stderr)
            return EXIT_INCOMPLETE_NOTICES
        folder = _copy_licenses(f"{name}-{version}", files, args.dest)
        packages.append(BundledPackage(name, version, _license_name(dist), folder))
    packages.append(_python_license(args.dest))
    notices = _notices(packages, source_url, project.get("Author-email") or project["Author"])
    (args.dest / NOTICES_FILE).write_text(notices, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
