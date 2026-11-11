"""Apply edits from a Markdown note onto the original .docx, touching only what changed.

```text
base .docx + base items --Patcher--> SequenceMatcher over block Markdown
  equal blocks     kept byte-for-byte
  replaced hunks   pair_hunk: edit similar blocks, insert or delete the rest
  edited blocks    token diff; unchanged tokens keep their runs and formatting
  new comments     comments part + commentsExtended threading
```
"""

from __future__ import annotations

from .diff import pair_hunk, tokens
from .patcher import PARA_KINDS, Patcher, apply_note
from .report import BaseMismatchError, ConflictError, Report

__all__ = [
    "PARA_KINDS",
    "BaseMismatchError",
    "ConflictError",
    "Patcher",
    "Report",
    "apply_note",
    "pair_hunk",
    "tokens",
]
