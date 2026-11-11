"""Package parts that the reader and the patcher look up: styles, numbering, and related parts."""

from __future__ import annotations

import io

from docx import Document
from docx.document import Document as DocxDocument
from docx.opc.part import Part, XmlPart
from lxml import etree

from ..ooxml import RT_NUMBERING, qn, wval

DEFAULT_NUM_FMT = "decimal"


def load_document(data: bytes) -> DocxDocument:
    return Document(io.BytesIO(data))


def part_by_reltype(part: Part, reltype: str) -> Part | None:
    for rel in part.rels.values():
        if rel.reltype == reltype and not rel.is_external:
            return rel.target_part
    return None


def part_xml(part: Part) -> etree._Element:
    """Return the root element of a part, whether python-docx parsed it or kept a blob."""
    if isinstance(part, XmlPart):
        return part.element
    return etree.fromstring(part.blob)


def is_on_attr(v: str | None) -> bool:
    return v is not None and v.lower() in ("1", "true", "on")


class Styles:
    def __init__(self, doc: DocxDocument) -> None:
        root = doc.styles.element
        self.by_id: dict[str, etree._Element] = {}
        self.default_para: str | None = None
        for s in root.findall(qn("w:style")):
            sid = s.get(qn("w:styleId"))
            self.by_id[sid] = s
            if s.get(qn("w:type")) == "paragraph" and is_on_attr(s.get(qn("w:default"))):
                self.default_para = sid

    def name(self, sid: str | None) -> str:
        s = self.by_id.get(sid or "")
        if s is None:
            return ""
        return wval(s.find(qn("w:name")), "") or ""

    def id_for_name(self, name: str) -> str | None:
        for sid, s in self.by_id.items():
            if (wval(s.find(qn("w:name")), "") or "").lower() == name.lower():
                return sid
        return None

    def numpr(self, sid: str | None) -> etree._Element | None:
        """The numbering properties of a style, following w:basedOn to the first style that has them."""
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            s = self.by_id.get(sid)
            if s is None:
                return None
            np = s.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
            if np is not None:
                return np
            sid = wval(s.find(qn("w:basedOn")))
        return None


class Numbering:
    def __init__(self, doc: DocxDocument) -> None:
        part = part_by_reltype(doc.part, RT_NUMBERING)
        self.root = part_xml(part) if part is not None else None

    def _num(self, root: etree._Element, num_id: str) -> etree._Element | None:
        for n in root.findall(qn("w:num")):
            if n.get(qn("w:numId")) == num_id:
                return n
        return None

    @staticmethod
    def _override_fmt(num: etree._Element, ilvl: int) -> str | None:
        for ov in num.findall(qn("w:lvlOverride")):
            if ov.get(qn("w:ilvl")) == str(ilvl):
                lvl = ov.find(qn("w:lvl"))
                if lvl is not None and lvl.find(qn("w:numFmt")) is not None:
                    return wval(lvl.find(qn("w:numFmt")), DEFAULT_NUM_FMT) or DEFAULT_NUM_FMT
        return None

    @staticmethod
    def _abstract_fmt(root: etree._Element, abs_id: str | None, ilvl: int) -> str | None:
        for a in root.findall(qn("w:abstractNum")):
            if a.get(qn("w:abstractNumId")) == abs_id:
                for lvl in a.findall(qn("w:lvl")):
                    if lvl.get(qn("w:ilvl")) == str(ilvl):
                        return wval(lvl.find(qn("w:numFmt")), DEFAULT_NUM_FMT) or DEFAULT_NUM_FMT
        return None

    def fmt(self, num_id: str, ilvl: int) -> str:
        """The number format of a list level: a level override first, then the abstract numbering definition."""
        if self.root is None:
            return DEFAULT_NUM_FMT
        num = self._num(self.root, num_id)
        if num is None:
            return DEFAULT_NUM_FMT
        found = self._override_fmt(num, ilvl)
        if found is not None:
            return found
        abs_id = wval(num.find(qn("w:abstractNumId")))
        return self._abstract_fmt(self.root, abs_id, ilvl) or DEFAULT_NUM_FMT
