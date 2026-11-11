"""Build runs, hyperlinks, and tracked-change marks from a token stream.

A stream entry is (token, source segment, change). The change is "eq" for a kept token, "ins" for new
text, and "del" for removed text. A kept or deleted token keeps the run properties it was read with; an
inserted token gets properties from the paragraph's template run plus its own bold, italic, and strike.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from docx.document import Document as DocxDocument
from lxml import etree

from ..inline import Seg
from ..ooxml import RPR_ORDER, RT_HYPERLINK, elements, insert_ordered, local, make, now_iso, qn
from ..reader import Reader

StreamEntry = tuple[str, Seg, str]
REVISION_ID_GAP = 1000
# Formatting that a segment states itself. A template run drops it so new text does not inherit it.
_SEGMENT_FORMATTING = ("w:b", "w:bCs", "w:i", "w:iCs", "w:strike", "w:dstrike", "w:rPrChange", "w:ins", "w:del")


class Revisions:
    """Creates tracked-change marks with ids above every revision id already in the body."""

    def __init__(self, body: etree._Element, author: str) -> None:
        ids = [
            int(e.get(qn("w:id")) or 0)
            for e in body.iter(qn("w:ins"), qn("w:del"), qn("w:pPrChange"), qn("w:rPrChange"))
            if (e.get(qn("w:id")) or "").isdigit()
        ]
        self._next = max(ids, default=0) + REVISION_ID_GAP
        self.author = author

    def mark(self, tag: str) -> etree._Element:
        self._next += 1
        return make(tag, {"w:id": str(self._next), "w:author": self.author, "w:date": now_iso()})


@dataclass
class _Group:
    """Adjacent tokens that become one run."""

    key: tuple[str, str | None, tuple[bool, bool, bool] | int, int | None]
    texts: list[str]
    seg: Seg
    change: str


@dataclass
class _BuiltRun:
    change: str
    link: str | None
    link_el: etree._Element | None
    run: etree._Element


def _mergeable(r: etree._Element) -> bool:
    return local(r) == "r" and all(local(c) in ("rPr", "t") for c in elements(r)) and r.find(qn("w:t")) is not None


def _same_rpr(a: etree._Element | None, b: etree._Element | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return etree.tostring(a, method="c14n") == etree.tostring(b, method="c14n")


def merge_runs(parent: etree._Element) -> None:
    """Join adjacent plain-text runs that share identical formatting."""
    prev = None
    for r in list(elements(parent)):
        if (
            prev is not None
            and _mergeable(prev)
            and _mergeable(r)
            and _same_rpr(prev.find(qn("w:rPr")), r.find(qn("w:rPr")))
        ):
            last = prev.findall(qn("w:t"))[-1]
            last.text = (last.text or "") + "".join(t.text or "" for t in r.findall(qn("w:t")))
            parent.remove(r)
            continue
        prev = r


class RunBuilder:
    def __init__(self, doc: DocxDocument, reader: Reader, revisions: Revisions, *, suggest: bool) -> None:
        self.doc = doc
        self.reader = reader
        self.revisions = revisions
        self.suggest = suggest

    @staticmethod
    def template_rpr(segs: list[Seg]) -> etree._Element | None:
        """Run properties for new text: the first unlinked run, without its own emphasis or revision marks."""
        src = next((s for s in segs if s.rpr is not None and not s.link), None)
        if src is None or src.rpr is None:
            return None
        rpr = copy.deepcopy(src.rpr)
        for tag in _SEGMENT_FORMATTING:
            for e in rpr.findall(qn(tag)):
                rpr.remove(e)
        return rpr

    def make_rpr(self, template: etree._Element | None, seg: Seg) -> etree._Element | None:
        rpr = copy.deepcopy(template) if template is not None else make("w:rPr")
        if seg.b:
            insert_ordered(rpr, make("w:b"), RPR_ORDER)
        if seg.i:
            insert_ordered(rpr, make("w:i"), RPR_ORDER)
        if seg.s:
            insert_ordered(rpr, make("w:strike"), RPR_ORDER)
        if seg.link:
            sid = self.reader.styles.id_for_name("Hyperlink")
            if sid:
                insert_ordered(rpr, make("w:rStyle", {"w:val": sid}), RPR_ORDER)
        return rpr if len(rpr) else None

    @staticmethod
    def make_run(text: str, rpr: etree._Element | None, *, deleted: bool = False) -> etree._Element:
        r = make("w:r")
        if rpr is not None:
            r.append(rpr)
        for part in re.split(r"(\n|\t)", text):
            if part == "\n":
                r.append(make("w:br"))
            elif part == "\t":
                r.append(make("w:tab"))
            elif part:
                t = make("w:delText" if deleted else "w:t", text=part)
                t.set(qn("xml:space"), "preserve")
                r.append(t)
        return r

    def hyperlink(self, url: str, link_el: etree._Element | None) -> etree._Element:
        """A w:hyperlink that copies an existing link's attributes, or relates a new target."""
        h = make("w:hyperlink")
        if link_el is not None:
            for k, v in link_el.attrib.items():
                h.set(k, v)
            return h
        if url.startswith("#"):
            h.set(qn("w:anchor"), url[1:])
        else:
            h.set(qn("r:id"), self.doc.part.relate_to(url, RT_HYPERLINK, is_external=True))
        h.set(qn("w:history"), "1")
        return h

    def _groups(self, stream: list[StreamEntry]) -> list[_Group]:
        groups: list[_Group] = []
        for text, seg, change in stream:
            if change == "del" and not self.suggest:
                continue
            key = (
                change,
                seg.link,
                seg.fmt if change == "ins" else id(seg.rpr),
                id(seg.link_el) if change != "ins" else None,
            )
            if groups and groups[-1].key == key:
                groups[-1].texts.append(text)
            else:
                groups.append(_Group(key, [text], seg, change))
        return groups

    def _built(self, g: _Group, template: etree._Element | None) -> _BuiltRun:
        seg = g.seg
        if g.change == "ins":
            rpr = self.make_rpr(template, seg)
        else:
            rpr = copy.deepcopy(seg.rpr) if seg.rpr is not None else None
        run = self.make_run("".join(g.texts), rpr, deleted=g.change == "del")
        return _BuiltRun(g.change, seg.link, seg.link_el if g.change != "ins" else None, run)

    def _append(self, container: etree._Element, br: _BuiltRun) -> None:
        """Append a run, wrapping a suggested change in w:ins or w:del and joining it with the previous mark."""
        if self.suggest and br.change in ("ins", "del"):
            last = container[-1] if len(container) else None
            if last is not None and local(last) == br.change:
                last.append(br.run)
            else:
                w = self.revisions.mark(f"w:{br.change}")
                w.append(br.run)
                container.append(w)
        else:
            container.append(br.run)

    def build(self, stream: list[StreamEntry], template: etree._Element | None) -> list[etree._Element]:
        """Turn a (token, segment, change) stream into runs, hyperlinks, and revision marks."""
        runs = [self._built(g, template) for g in self._groups(stream)]
        holder = make("w:p")
        k = 0
        while k < len(runs):
            link = runs[k].link
            group = []
            while k < len(runs) and runs[k].link == link:
                group.append(runs[k])
                k += 1
            container = holder
            if link:
                link_el = next((g.link_el for g in group if g.link_el is not None), None)
                container = self.hyperlink(link, link_el)
                holder.append(container)
            for br in group:
                self._append(container, br)
        merge_runs(holder)
        for h in holder.findall(qn("w:hyperlink")):
            merge_runs(h)
        return list(holder)
