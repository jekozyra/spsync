"""Inline Markdown <-> Word run segments.

The renderer and parser are designed as a pair: parse(render(x)) recovers the same text and
formatting, so unchanged paragraphs compare equal and are never rewritten.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Any

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
    rpr: Any = field(default=None, compare=False, repr=False)
    link_el: Any = field(default=None, compare=False, repr=False)
    # Pending tracked change, shown as ==inserted== or ~~deleted~~ (display only).
    rev: str | None = None

    @property
    def fmt(self):
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
        idx = re.match(r"\d+", md).end()
        return md[:idx] + "\\" + md[idx:]
    return "\\" + md


def _merge(segs: list[Seg]) -> list[Seg]:
    out: list[Seg] = []
    for s in segs:
        if not s.text:
            continue
        if out and out[-1].fmt == s.fmt and out[-1].link == s.link and out[-1].rev == s.rev and "\n" not in s.text and "\n" not in out[-1].text:
            out[-1] = Seg(out[-1].text + s.text, s.b, s.i, s.s, s.link, rev=s.rev)
        else:
            out.append(Seg(s.text, s.b, s.i, s.s, s.link, rev=s.rev))
    return out


def _wrap(text: str, b: bool, i: bool, s: bool, rev: str | None = None) -> str:
    core = text.strip()
    if not core or not (b or i or s or rev):
        return escape(text)
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    open_ = {"ins": "==", "del": "~~"}.get(rev or "", "") + ("~~" if s and rev != "del" else "") + ("**" if b else "") + ("*" if i else "")
    return lead + open_ + escape(core) + open_[::-1] + trail


def render_inline(segs: list[Seg]) -> str:
    # Split line breaks into their own segments so markers never span them.
    pieces: list[Seg] = []
    for s in segs:
        for part in re.split(r"(\n)", s.text):
            if part:
                pieces.append(Seg(part, s.b, s.i, s.s, s.link, rev=s.rev))
    merged = _merge(pieces)
    out: list[str] = []
    k = 0
    while k < len(merged):
        seg = merged[k]
        if seg.link:
            group = []
            while k < len(merged) and merged[k].link == seg.link:
                group.append(merged[k])
                k += 1
            inner = "".join("<br>" if g.text == "\n" else _wrap(g.text, g.b, g.i, g.s, g.rev) for g in group)
            out.append(f"[{inner}]({_encode_url(seg.link)})")
            continue
        out.append("<br>" if seg.text == "\n" else _wrap(seg.text, seg.b, seg.i, seg.s, seg.rev))
        k += 1
    return "".join(out)


def _tokenize(s: str):
    toks: list[tuple] = []
    buf: list[str] = []

    def flush():
        if buf:
            toks.append(("t", "".join(buf)))
            buf.clear()

    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in PUNCT:
            buf.append(s[i + 1])
            i += 2
            continue
        m = BR_RE.match(s, i)
        if m:
            flush()
            toks.append(("br",))
            i = m.end()
            continue
        if c == "\n":
            flush()
            toks.append(("br",))
            i += 1
            continue
        if c == "[":
            m = LINK_RE.match(s, i)
            if m:
                flush()
                toks.append(("link", m.group(1), _decode_url(m.group(2))))
                i = m.end()
                continue
        if s.startswith("**", i):
            flush()
            toks.append(["m", "b", "**"])
            i += 2
            continue
        if s.startswith("~~", i):
            flush()
            toks.append(["m", "s", "~~"])
            i += 2
            continue
        if c == "*":
            flush()
            toks.append(["m", "i", "*"])
            i += 1
            continue
        if c == "_":
            prev = s[i - 1] if i else ""
            nxt = s[i + 1] if i + 1 < n else ""
            if not (prev.isalnum() and nxt.isalnum()):
                flush()
                toks.append(["m", "u", "_"])
                i += 1
                continue
        buf.append(c)
        i += 1
    flush()
    # Pair markers; unpaired ones become literal text.
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


def parse_inline(s: str, link: str | None = None, base=(False, False, False)) -> list[Seg]:
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
