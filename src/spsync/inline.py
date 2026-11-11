"""Inline Markdown <-> Word run segments.

The renderer and parser are designed as a pair: parse(render(x)) recovers the same text and
formatting, so unchanged paragraphs compare equal and are never rewritten.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from lxml import etree

PUNCT = set(string.punctuation)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
LINK_RE = re.compile(r"\[((?:\\.|[^\]\\])*)\]\(([^)\s]+)\)")


@dataclass
class Seg:
    text: str
    b: bool = False
    i: bool = False
    s: bool = False
    link: str | None = None
    # Source run properties and hyperlink element when read from a document.
    rpr: etree._Element | None = field(default=None, compare=False, repr=False)
    link_el: etree._Element | None = field(default=None, compare=False, repr=False)
    # Pending tracked change, shown as ==inserted== or ~~deleted~~ (display only).
    rev: str | None = None
    # Markdown emitted verbatim instead of the text (for example an image embed).
    raw: str | None = None

    @property
    def fmt(self) -> tuple[bool, bool, bool]:
        return (self.b, self.i, self.s)


def _encode_url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _decode_url(url: str) -> str:
    return url.replace("%20", " ").replace("%28", "(").replace("%29", ")")


def escape(text: str) -> str:
    out = []
    n = len(text)
    for k, ch in enumerate(text):
        prev = text[k - 1] if k else ""
        nxt = text[k + 1] if k + 1 < n else ""
        if ch in "\\*[]`$":
            out.append("\\" + ch)
        elif ch == "_" and not (prev.isalnum() and nxt.isalnum()):
            out.append("\\_")
        elif ch in "~=%" and (nxt == ch or prev == ch):
            out.append("\\" + ch)
        elif ch == "<" and (nxt.isalpha() or nxt == "/"):
            out.append("\\<")
        else:
            out.append(ch)
    return "".join(out)


_BLOCK_START = re.compile(r"^(#|>|\||[-+] |\d+[.)](\s|$))")


def escape_block_start(md: str) -> str:
    """Keep paragraph text from being read back as a heading, list, quote, or table."""
    if re.fullmatch(r"[-_*]{3,}", md.strip()):
        return "\\" + md
    m = _BLOCK_START.match(md)
    if not m:
        return md
    tok = m.group(1)
    if tok[0].isdigit():
        idx = len(tok) - len(tok.lstrip("0123456789"))
        return md[:idx] + "\\" + md[idx:]
    return "\\" + md


def _merge(segs: list[Seg]) -> list[Seg]:
    out: list[Seg] = []
    for s in segs:
        if not s.text:
            continue
        if s.raw is not None or (out and out[-1].raw is not None):
            out.append(s)
            continue
        if (
            out
            and out[-1].fmt == s.fmt
            and out[-1].link == s.link
            and out[-1].rev == s.rev
            and "\n" not in s.text
            and "\n" not in out[-1].text
        ):
            out[-1] = Seg(out[-1].text + s.text, s.b, s.i, s.s, s.link, rev=s.rev)
        else:
            out.append(Seg(s.text, s.b, s.i, s.s, s.link, rev=s.rev))
    return out


def _wrap(text: str, b: bool, i: bool, s: bool, rev: str | None = None) -> str:
    core = text.strip()
    if not core or not (b or i or s or rev):
        return escape(text)
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    open_ = (
        {"ins": "==", "del": "~~"}.get(rev or "", "")
        + ("~~" if s and rev != "del" else "")
        + ("**" if b else "")
        + ("*" if i else "")
    )
    return lead + open_ + escape(core) + open_[::-1] + trail


def render_inline(segs: list[Seg]) -> str:
    # Split line breaks into their own segments so markers never span them.
    pieces: list[Seg] = []
    for s in segs:
        if s.raw is not None:
            pieces.append(s)
            continue
        for part in re.split(r"(\n)", s.text):
            if part:
                pieces.append(Seg(part, s.b, s.i, s.s, s.link, rev=s.rev))
    merged = _merge(pieces)
    out: list[str] = []
    k = 0
    while k < len(merged):
        seg = merged[k]
        if seg.raw is not None:
            out.append(seg.raw)
            k += 1
            continue
        if seg.link:
            group = []
            while k < len(merged) and merged[k].link == seg.link:
                group.append(merged[k])
                k += 1
            inner = "".join(
                g.raw if g.raw is not None else "<br>" if g.text == "\n" else _wrap(g.text, g.b, g.i, g.s, g.rev)
                for g in group
            )
            out.append(f"[{inner}]({_encode_url(seg.link)})")
            continue
        out.append("<br>" if seg.text == "\n" else _wrap(seg.text, seg.b, seg.i, seg.s, seg.rev))
        k += 1
    return "".join(out)


# A token is ("t", text), ("br",), ("link", label, url), or ("m", kind, marker) for an emphasis marker.
Token = tuple[str, ...]

# Longer markers first, so that `**` is not read as two `*` markers.
_MARKERS = (("**", "b"), ("~~", "s"), ("*", "i"))


def _marker_at(s: str, i: int) -> tuple[str, str] | None:
    """The emphasis kind and marker that start at `i`. `_` inside a word is text, not a marker."""
    for mark, kind in _MARKERS:
        if s.startswith(mark, i):
            return kind, mark
    if s[i] == "_":
        prev = s[i - 1] if i else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if not (prev.isalnum() and nxt.isalnum()):
            return "u", "_"
    return None


def _special_at(s: str, i: int) -> tuple[Token, int] | None:
    """The line break, link, or marker token that starts at `i`, and the index after it."""
    m = BR_RE.match(s, i)
    if m:
        return ("br",), m.end()
    if s[i] == "\n":
        return ("br",), i + 1
    if s[i] == "[":
        m = LINK_RE.match(s, i)
        if m:
            return ("link", m.group(1), _decode_url(m.group(2))), m.end()
    marker = _marker_at(s, i)
    if marker:
        kind, mark = marker
        return ("m", kind, mark), i + len(mark)
    return None


def _scan(s: str) -> list[Token]:
    toks: list[Token] = []
    buf: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1] in PUNCT:
            buf.append(s[i + 1])
            i += 2
            continue
        found = _special_at(s, i)
        if found is None:
            buf.append(s[i])
            i += 1
            continue
        if buf:
            toks.append(("t", "".join(buf)))
            buf.clear()
        tok, i = found
        toks.append(tok)
    if buf:
        toks.append(("t", "".join(buf)))
    return toks


def _tokenize(s: str) -> list[Token]:
    """Tokens for `s`, with unpaired emphasis markers turned back into text."""
    toks = _scan(s)
    open_: dict[str, int] = {}
    paired: set[int] = set()
    for idx, t in enumerate(toks):
        if t[0] != "m":
            continue
        kind = t[1]
        if kind in open_:
            paired.add(open_.pop(kind))
            paired.add(idx)
        else:
            open_[kind] = idx
    return [t if t[0] != "m" or idx in paired else ("t", t[2]) for idx, t in enumerate(toks)]


def parse_inline(s: str, link: str | None = None, base: tuple[bool, bool, bool] = (False, False, False)) -> list[Seg]:
    b, i, st = base
    u = False
    out: list[Seg] = []
    for t in _tokenize(s):
        if t[0] == "t":
            out.append(Seg(t[1], b, i or u, st, link))
        elif t[0] == "br":
            out.append(Seg("\n", b, i or u, st, link))
        elif t[0] == "link":
            out.extend(parse_inline(t[1], t[2], (b, i or u, st)))
        else:
            kind = t[1]
            if kind == "b":
                b = not b
            elif kind == "i":
                i = not i
            elif kind == "u":
                u = not u
            elif kind == "s":
                st = not st
    return _merge(out)


def plain(segs: list[Seg]) -> str:
    return "".join(s.text for s in segs)
