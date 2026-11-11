"""Block pairing and word tokens for the patcher and the Word backend."""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Protocol

TOKEN = re.compile(r"\n|\t|[^\S\n\t]+|\w+|[^\w\s]")
_PREFIX = re.compile(r"^(#{1,6}\s+|[\t ]*(?:[-*+]|\d+[.)])\s+|>\s?)")
PAIR_THRESHOLD = 0.5
SNIPPET_CHARS = 60

# ("mod", old index, new index), ("del", old index), or ("ins", new index), all relative to the hunk.
HunkOp = tuple[str, int, int] | tuple[str, int]


class Markdown(Protocol):
    """A block with Markdown text, such as a base Item or a parsed note PItem."""

    md: str


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _PREFIX.sub("", a), _PREFIX.sub("", b), autojunk=False).ratio()


def pair_hunk(old: Sequence[Markdown], new: Sequence[Markdown], threshold: float = PAIR_THRESHOLD) -> list[HunkOp]:
    """Order-preserving pairing of a replaced hunk: edit similar blocks, insert or delete the rest."""
    ops: list[HunkOp] = []
    j0 = 0
    for i, o in enumerate(old):
        best, best_j = 0.0, None
        for j in range(j0, len(new)):
            r = _similarity(o.md, new[j].md)
            if r > best:
                best, best_j = r, j
        if best_j is not None and best >= threshold:
            ops.extend(("ins", j) for j in range(j0, best_j))
            ops.append(("mod", i, best_j))
            j0 = best_j + 1
        else:
            ops.append(("del", i))
    ops.extend(("ins", j) for j in range(j0, len(new)))
    return ops


def snippet(md: str) -> str:
    """One line of a block for a warning message."""
    s = md.replace("\n", " ")
    return s if len(s) <= SNIPPET_CHARS else s[: SNIPPET_CHARS - 3] + "..."


def tokens(text: str) -> list[str]:
    """Words, punctuation, runs of spaces, tabs, and line breaks. The diff unit for an edited paragraph."""
    return TOKEN.findall(text)
