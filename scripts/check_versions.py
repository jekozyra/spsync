"""Check that the three manifests declare one spsync version.

```text
pyproject.toml                  [project] version   the CLI package
obsidian-plugin/manifest.json   version             the plugin, read by Obsidian and BRAT
obsidian-plugin/package.json    version             the plugin package
```

The pre-commit hook runs this script with no options. The release workflow adds `--expect` with the
version from the release tag. The script exits with 0 when every manifest declares the expected
version, and with 1 otherwise. Without `--expect`, the expected version is the pyproject.toml version.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = "pyproject.toml"
MANIFESTS = (PYPROJECT, "obsidian-plugin/manifest.json", "obsidian-plugin/package.json")
EXIT_MISMATCH = 1


def _read_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == PYPROJECT:
        version = tomllib.loads(text).get("project", {}).get("version")
    else:
        version = json.loads(text).get("version")
    if not isinstance(version, str):
        return "missing"
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the spsync manifests declare one version.")
    parser.add_argument("--root", type=Path, default=REPO, help="The repository root")
    parser.add_argument("--expect", help="The version that every manifest must declare, such as 0.1.0")
    args = parser.parse_args()
    versions = {name: _read_version(args.root / name) for name in MANIFESTS}
    expected = args.expect or versions[PYPROJECT]
    if all(version == expected for version in versions.values()):
        print(f"spsync version {expected}")
        return 0
    for name, version in versions.items():
        print(f"{name}: {version}", file=sys.stderr)
    print(f"check_versions.py: every manifest must declare version {expected}.", file=sys.stderr)
    return EXIT_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
