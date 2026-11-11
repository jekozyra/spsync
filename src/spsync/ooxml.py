"""Small OOXML helpers shared by the reader and the patcher."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
W = NS["w"]

RT_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
RT_COMMENTS_EXT = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
RT_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
RT_NUMBERING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
CT_COMMENTS_EXT = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"


def qn(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


def make(tag: str, attrs: dict[str, str] | None = None, text: str | None = None) -> etree._Element:
    e = etree.Element(qn(tag))
    for k, v in (attrs or {}).items():
        e.set(qn(k), v)
    if text is not None:
        e.text = text
    return e


def local(e: etree._Element) -> str:
    return etree.QName(e).localname


def ns_of(e: etree._Element) -> str:
    return etree.QName(e).namespace or ""


def elements(parent: etree._Element) -> list[etree._Element]:
    """Child elements, skipping XML comments and processing instructions."""
    return [c for c in parent if isinstance(c.tag, str)]


def int_attr(e: etree._Element, tag: str) -> int:
    """An integer attribute, such as a comment's w:id. A missing attribute is a malformed document."""
    v = e.get(qn(tag))
    if v is None:
        raise ValueError(f"<{local(e)}> has no {tag} attribute")
    return int(v)


def is_on(e: etree._Element | None) -> bool:
    if e is None:
        return False
    v = e.get(qn("w:val"))
    return v is None or v.lower() not in ("0", "false", "off", "none")


def wval(e: etree._Element | None, default: str | None = None) -> str | None:
    if e is None:
        return default
    return e.get(qn("w:val"), default)


def new_para_id() -> str:
    return f"{random.randint(1, 0x7FFFFFFE):08X}"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Child order from the WordprocessingML schema. Word Online rejects out-of-order children.
RPR_ORDER = [
    "rStyle",
    "rFonts",
    "b",
    "bCs",
    "i",
    "iCs",
    "caps",
    "smallCaps",
    "strike",
    "dstrike",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "noProof",
    "snapToGrid",
    "vanish",
    "webHidden",
    "color",
    "spacing",
    "w",
    "kern",
    "position",
    "sz",
    "szCs",
    "highlight",
    "u",
    "effect",
    "bdr",
    "shd",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "rPrChange",
]
PPR_ORDER = [
    "pStyle",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "framePr",
    "widowControl",
    "numPr",
    "suppressLineNumbers",
    "pBdr",
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
]


def insert_ordered(parent: etree._Element, child: etree._Element, order: list[str]) -> etree._Element:
    """Insert `child` into `parent`, replacing a same-named child, honoring schema order."""
    name = local(child)
    for existing in parent.findall(etree.QName(child)):
        parent.remove(existing)
    rank = order.index(name) if name in order else len(order)
    for c in elements(parent):
        cname = local(c)
        crank = order.index(cname) if cname in order else len(order)
        if crank > rank:
            c.addprevious(child)
            return child
    parent.append(child)
    return child


def ensure_child(parent: etree._Element, tag: str, order: list[str]) -> etree._Element:
    found = parent.find(qn(tag))
    if found is not None:
        return found
    return insert_ordered(parent, make(tag), order)
