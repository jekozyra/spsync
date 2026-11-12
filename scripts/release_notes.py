"""Print the CHANGELOG.md section of one version, for the release notes.

```text
## [Unreleased]
## [1.2.0] - 2026-11-12   <-- release_notes.py 1.2.0 prints the lines below this heading,
### Added                     up to the next "## " heading or the link definitions
- ...
## [1.1.0] - 2026-10-01
[1.2.0]: https://github.com/...
```

The release workflow runs this script before it builds anything. The script exits with 1 when the
changelog has no section for the version, or when the section is empty, so that every release has notes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
SECTION_PREFIX = "## "
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]: ")
EXIT_NO_NOTES = 1


def _section(changelog: str, version: str) -> str:
    heading = f"{SECTION_PREFIX}[{version}]"
    body: list[str] = []
    inside = False
    for line in changelog.splitlines():
        if line.startswith(SECTION_PREFIX) or LINK_DEFINITION.match(line):
            if inside:
                break
            inside = line == heading or line.startswith(f"{heading} ")
            continue
        if inside:
            body.append(line)
    return "\n".join(body).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the CHANGELOG.md section of one version.")
    parser.add_argument("version", help="The version without the v prefix, such as 0.1.0")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="The changelog file")
    args = parser.parse_args()
    notes = _section(args.changelog.read_text(encoding="utf-8"), args.version)
    if not notes:
        print(f"release_notes.py: {args.changelog.name} has no notes for version {args.version}.", file=sys.stderr)
        return EXIT_NO_NOTES
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
