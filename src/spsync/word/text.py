"""Text matching between the base document and the paragraph text that Word reports."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

PLACEHOLDER = re.compile(r"‹[^›]*›")
CONTEXT_TOKEN = re.compile(r"\w+|\s+|[^\w\s]")
ALIGN_THRESHOLD = 0.6
MAX_CONTEXT_CHARS = 240
SNIP_CHARS = 50
MAX_LIST_STYLE_LEVEL = 5
FIRST_PRINTABLE = 32

STYLE = {
    "h1": "style heading1",
    "h2": "style heading2",
    "h3": "style heading3",
    "h4": "style heading4",
    "h5": "style heading5",
    "h6": "style heading6",
    "p": "style normal",
    "quote": "style quote",
}


def word_raw(p: str) -> str:
    """Word paragraph content without its paragraph or cell mark; line breaks as \\n."""
    return p.rstrip("\r\x07").replace("\x0b", "\n")


def norm(s: str) -> str:
    """Text for comparison: no placeholders, no control characters, and single spaces."""
    s = PLACEHOLDER.sub("", s)
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= FIRST_PRINTABLE)
    return " ".join(s.split())


def offset_map(base: str, word: str) -> list[int]:
    """Map each offset in `base` (0..len) to an offset in `word`."""
    m = [0] * (len(base) + 1)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, word, autojunk=False).get_opcodes():
        for k in range(i1, i2 + 1):
            m[k] = j1 + (k - i1) if tag == "equal" else (j1 if k < i2 else j2)
    m[len(base)] = len(word)
    return m


def align(base_texts: list[str], word_texts: list[str]) -> list[int | None]:
    """Order-preserving match of base paragraphs to Word paragraph indices (0-based)."""
    bn = [norm(t) for t in base_texts]
    wn = [norm(word_raw(t)) for t in word_texts]
    out: list[int | None] = [None] * len(bn)
    sm = SequenceMatcher(None, bn, wn, autojunk=False)
    prev_b = prev_w = 0
    for b0, w0, size in sm.get_matching_blocks():
        # Fuzzy-match leftovers in the gap (for paragraphs with images or fields).
        j = prev_w
        for i in range(prev_b, b0):
            best, best_j = 0.0, None
            for k in range(j, w0):
                r = SequenceMatcher(None, bn[i], wn[k], autojunk=False).ratio()
                if r > best:
                    best, best_j = r, k
            if best_j is not None and best >= ALIGN_THRESHOLD:
                out[i] = best_j
                j = best_j + 1
        for k in range(size):
            out[b0 + k] = w0 + k
        prev_b, prev_w = b0 + size, w0 + size
    return out


def unique_context(text: str, a: int, b: int, limit: int = MAX_CONTEXT_CHARS) -> tuple[int, int]:
    """Grow [a, b) by whole tokens until text[a:b] occurs once in `text`."""
    toks = [(m.start(), m.end()) for m in CONTEXT_TOKEN.finditer(text)]
    lo, hi = a, b
    while True:
        s = text[lo:hi]
        if (s and text.count(s) == 1) or hi - lo >= limit or (lo == 0 and hi == len(text)):
            return lo, hi
        before = [t for t in toks if t[1] <= lo]
        after = [t for t in toks if t[0] >= hi]
        if before:
            lo = before[-1][0]
        if after:
            hi = after[0][1]
        if not before and not after:
            return lo, hi


def find_escape(s: str) -> str:
    """Escape text for Word's find: `^` is the escape character, `^l` a line break, `^t` a tab."""
    return s.replace("^", "^^").replace("\n", "^l").replace("\t", "^t")


def style_enum(kind: str, level: int) -> str:
    """The Word style enumeration for a block kind and list level."""
    if kind in ("ul", "ol"):
        base = "style list bullet" if kind == "ul" else "style list number"
        return base + (str(min(level + 1, MAX_LIST_STYLE_LEVEL)) if level else "")
    return STYLE.get(kind, "style normal")


def snip(s: str) -> str:
    """One line of a block for an op label or a warning."""
    s = s.replace("\n", " ")
    return s if len(s) <= SNIP_CHARS else s[: SNIP_CHARS - 3] + "..."
