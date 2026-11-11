"""Apply edits from a Markdown note onto the original .docx, touching only what changed."""

from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from docx.opc.packuri import PackURI
from docx.opc.part import Part
from lxml import etree

from .inline import Seg, parse_inline
from .mdparse import PItem
from .ooxml import (
    CT_COMMENTS_EXT,
    PPR_ORDER,
    RPR_ORDER,
    RT_COMMENTS,
    RT_COMMENTS_EXT,
    RT_HYPERLINK,
    elements,
    ensure_child,
    insert_ordered,
    local,
    make,
    new_para_id,
    now_iso,
    qn,
    wval,
)
from .reader import Item, Reader, load_document, part_by_reltype, part_xml

PARA_RPR_ORDER = ["ins", "del", "moveFrom", "moveTo"] + [
    x for x in RPR_ORDER if x not in ("ins", "del", "moveFrom", "moveTo")
]
TOKEN = re.compile(r"\n|\t|[^\S\n\t]+|\w+|[^\w\s]")
PARA_KINDS = {"h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "p", "quote"}


class ConflictError(Exception):
    pass


class BaseMismatchError(Exception):
    pass


@dataclass
class Report:
    modified: int = 0
    inserted: int = 0
    deleted: int = 0
    comments: int = 0
    replies: int = 0
    resolved: int = 0
    private_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any((self.modified, self.inserted, self.deleted, self.comments, self.replies, self.resolved))

    def summary(self) -> str:
        parts = [
            f"{self.modified} edited",
            f"{self.inserted} added",
            f"{self.deleted} removed",
            f"{self.comments} comments",
            f"{self.replies} replies",
        ]
        if self.resolved:
            parts.append(f"{self.resolved} resolution changes")
        return ", ".join(parts)


_PREFIX = re.compile(r"^(#{1,6}\s+|[\t ]*(?:[-*+]|\d+[.)])\s+|>\s?)")


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _PREFIX.sub("", a), _PREFIX.sub("", b), autojunk=False).ratio()


def pair_hunk(old: list, new: list, threshold: float = 0.5) -> list[tuple]:
    """Order-preserving pairing of a replaced hunk: edit similar blocks, insert or delete the rest."""
    ops: list[tuple] = []
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


def _snippet(md: str) -> str:
    s = md.replace("\n", " ")
    return s if len(s) <= 60 else s[:57] + "..."


def _tokens(text: str) -> list[str]:
    return TOKEN.findall(text)


class Patcher:
    def __init__(
        self, base_docx: bytes, base_items: list[Item], *, author: str, initials: str = "", suggest: bool = False
    ):
        self.doc = load_document(base_docx)
        self.reader = Reader(self.doc)
        self.body = self.doc.element.body
        self.children = elements(self.body)
        self.base_items = base_items
        self.base_blocks = [it for it in base_items if it.t == "block"]
        self.base_comment_done = {it.id: it.done for it in base_items if it.t == "comment"}
        self.author = author or "spsync"
        self.initials = initials
        self.suggest = suggest
        self.report = Report()
        self.index_of: dict[int, int] = {}
        self._ext = None
        ids = [
            int(e.get(qn("w:id")))
            for e in self.body.iter(qn("w:ins"), qn("w:del"), qn("w:pPrChange"), qn("w:rPrChange"))
            if (e.get(qn("w:id")) or "").isdigit()
        ]
        self._rev = max(ids, default=0) + 1000
        self._check_base()

    # ---- setup ----
    def _check_base(self):
        for b in self.base_blocks:
            if b.i is None or b.i >= len(self.children):
                raise BaseMismatchError("Saved base document does not match its block map. Pull again.")
            want = {"table": ("tbl",), "raw": ("sdt", "p")}.get(b.kind, ("p",))
            if local(self.children[b.i]) not in want:
                raise BaseMismatchError("Saved base document does not match its block map. Pull again.")
            self.index_of[id(self.children[b.i])] = b.i

    def elem(self, b: Item):
        return self.children[b.i]

    def rev(self, tag: str):
        self._rev += 1
        return make(tag, {"w:id": str(self._rev), "w:author": self.author, "w:date": now_iso()})

    # ---- main entry ----
    def apply(self, new_items: list[PItem]) -> bytes:
        if any(it.t == "conflict" for it in new_items):
            raise ConflictError("The note still has [!conflict] callouts. Resolve them and delete the callouts first.")
        new_blocks: list[PItem] = []
        attach: list[tuple[int, PItem]] = []
        existing: list[PItem] = []
        for it in new_items:
            if it.t == "block":
                new_blocks.append(it)
            elif it.t == "newcomment":
                attach.append((len(new_blocks) - 1, it))
            elif it.t == "comment":
                existing.append(it)

        base = self.base_blocks
        sm = SequenceMatcher(None, [b.md for b in base], [b.md for b in new_blocks], autojunk=False)
        result: list = [None] * len(new_blocks)
        anchor = None
        to_delete: list[Item] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    result[j1 + k] = self.elem(base[i1 + k])
                    anchor = result[j1 + k]
                continue
            for op in pair_hunk(base[i1:i2], new_blocks[j1:j2]):
                if op[0] == "mod":
                    old, j = base[i1 + op[1]], j1 + op[2]
                    el = self.modify(old, new_blocks[j], to_delete)
                    result[j] = el
                    anchor = el if el is not None else self.elem(old)
                elif op[0] == "del":
                    to_delete.append(base[i1 + op[1]])
                    anchor = self.elem(base[i1 + op[1]])
                else:
                    j = j1 + op[1]
                    el = self.insert(new_blocks[j], anchor)
                    result[j] = el
                    if el is not None:
                        anchor = el

        for b in to_delete:
            self.delete(b)
        for bi, c in attach:
            target = self._target(result, bi)
            if target is None:
                self.report.warnings.append(f"Could not place comment: {_snippet(c.text)}")
                continue
            self.add_comment(target, c)
        for c in existing:
            if c.id in self.base_comment_done and c.done != self.base_comment_done[c.id]:
                self.set_done(c.id, c.done)
        return self.save()

    def _target(self, result, bi):
        bi = max(bi, 0)
        for k in range(min(bi, len(result) - 1), -1, -1):
            el = result[k]
            if el is not None and el.getparent() is not None:
                return el
        for el in result:
            if el is not None and el.getparent() is not None:
                return el
        return None

    def save(self) -> bytes:
        if self._ext is not None:
            part, root, is_blob = self._ext
            if is_blob:
                part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()

    # ---- block operations ----
    def modify(self, old: Item, new: PItem, to_delete: list[Item]):
        el = self.elem(old)
        if old.locked:
            self.report.warnings.append(
                f"Skipped edit to a block Obsidian can't safely change ({old.lock_reason}): {_snippet(old.md)}"
            )
            return el
        if old.kind not in PARA_KINDS or new.kind not in PARA_KINDS:
            to_delete.append(old)
            return self.insert(new, el)
        if (old.kind, old.level) != (new.kind, new.level):
            self.set_ppr(el, new.kind, new.level)
        self.rewrite(el, new.content)
        self.report.modified += 1
        return el

    def place(self, el, anchor):
        if anchor is None:
            first = self.elem(self.base_blocks[0]) if self.base_blocks else None
            if first is not None:
                first.addprevious(el)
            else:
                sect = self.body.find(qn("w:sectPr"))
                if sect is not None:
                    sect.addprevious(el)
                else:
                    self.body.append(el)
            self.index_of[id(el)] = 0
        else:
            anchor.addnext(el)
            self.index_of[id(el)] = self.index_of.get(id(anchor), 0)
        return el

    def insert(self, new: PItem, anchor):
        if new.kind == "raw":
            self.report.private_skipped += 1
            return None
        self.report.inserted += 1
        if new.kind == "table":
            return self.place(self.make_table(new.md), anchor)
        if new.kind == "code":
            last = anchor
            for line in new.content.split("\n") or [""]:
                rpr = make("w:rPr")
                rpr.append(make("w:rFonts", {"w:ascii": "Consolas", "w:hAnsi": "Consolas", "w:cs": "Consolas"}))
                p = self.new_para("p", 0, [Seg(line)], rpr_override=rpr, near=last)
                last = self.place(p, last)
            return last
        return self.place(self.new_para(new.kind, new.level, parse_inline(new.content), near=anchor), anchor)

    def new_para(self, kind, level, segs, rpr_override=None, near=None):
        p = make("w:p")
        ppr, ref_p = self.ref_ppr(kind, level, near)
        if ppr is not None:
            p.append(ppr)
        template = (
            rpr_override
            if rpr_override is not None
            else self.template_rpr(self.reader.segments(ref_p)[0] if ref_p is not None else [])
        )
        stream = [(t, s, "ins") for s in segs for t in _tokens(s.text)]
        for node in self.build(stream, template):
            p.append(node)
        if self.suggest:
            ppr = p.find(qn("w:pPr"))
            if ppr is None:
                ppr = make("w:pPr")
                p.insert(0, ppr)
            mark = ensure_child(ppr, "w:rPr", PPR_ORDER)
            insert_ordered(mark, self.rev("w:ins"), PARA_RPR_ORDER)
        return p

    def delete(self, b: Item):
        el = self.elem(b)
        if el.getparent() is None:
            return
        if not self.suggest:
            el.getparent().remove(el)
            self.report.deleted += 1
            return
        if b.locked or local(el) != "p":
            self.report.warnings.append(
                f"Skipped suggested deletion of a block Obsidian can't safely change ({b.lock_reason or b.kind}): {_snippet(b.md)}"
            )
            return
        for r in list(el.iter(qn("w:r"))):
            if r.find(qn("w:commentReference")) is not None:
                continue
            if local(r.getparent()) in ("ins", "del"):
                continue
            d = self.rev("w:del")
            r.addprevious(d)
            d.append(r)
            for t in r.findall(qn("w:t")):
                t.tag = qn("w:delText")
        ppr = el.find(qn("w:pPr"))
        if ppr is None:
            ppr = make("w:pPr")
            el.insert(0, ppr)
        mark = ensure_child(ppr, "w:rPr", PPR_ORDER)
        insert_ordered(mark, self.rev("w:del"), PARA_RPR_ORDER)
        self.report.deleted += 1

    # ---- paragraph properties ----
    def ref_ppr(self, kind, level, near):
        """Copy paragraph properties from the closest existing paragraph of the same kind."""
        near_idx = self.index_of.get(id(near), 0) if near is not None else 0
        cands = [b for b in self.base_blocks if b.kind == kind and not b.locked]
        same = [b for b in cands if b.level == level] or cands
        before = [b for b in same if b.i <= near_idx]
        best = (before[-1] if before else same[0]) if same else None
        if best is not None:
            ref_p = self.elem(best)
            src = ref_p.find(qn("w:pPr"))
            ppr = copy.deepcopy(src) if src is not None else make("w:pPr")
            self._clean_ppr(ppr)
            if kind in ("ul", "ol") and best.level != level:
                self._set_level(ppr, level)
            return ppr, ref_p
        name = {
            "h1": "heading 1",
            "h2": "heading 2",
            "h3": "heading 3",
            "h4": "heading 4",
            "h5": "heading 5",
            "h6": "heading 6",
            "ul": "List Bullet" + (f" {level + 1}" if level else ""),
            "ol": "List Number" + (f" {level + 1}" if level else ""),
            "quote": "Quote",
        }.get(kind)
        sid = self.reader.styles.id_for_name(name) if name else None
        if sid is None and kind in ("ul", "ol") and level:
            sid = self.reader.styles.id_for_name("List Bullet" if kind == "ul" else "List Number")
        if sid is None:
            if kind in ("ul", "ol", "quote") or kind.startswith("h"):
                self.report.warnings.append(f"No matching Word style for new {kind} block; used body text style.")
            p_cands = [b for b in self.base_blocks if b.kind == "p" and not b.locked]
            if p_cands and kind != "p":
                return self.ref_ppr("p", 0, near)
            return None, None
        ppr = make("w:pPr")
        ppr.append(make("w:pStyle", {"w:val": sid}))
        return ppr, None

    def _clean_ppr(self, ppr):
        for tag in ("w:sectPr", "w:pPrChange"):
            for e in ppr.findall(qn(tag)):
                ppr.remove(e)
        mark = ppr.find(qn("w:rPr"))
        if mark is not None:
            for tag in ("w:ins", "w:del", "w:moveFrom", "w:moveTo", "w:rPrChange"):
                for e in mark.findall(qn(tag)):
                    mark.remove(e)

    def _set_level(self, ppr, level):
        np = ppr.find(qn("w:numPr"))
        if np is None:
            style_np = self.reader.styles.numpr(wval(ppr.find(qn("w:pStyle"))))
            if style_np is None:
                return
            np = make("w:numPr")
            np.append(make("w:ilvl", {"w:val": str(level)}))
            np.append(make("w:numId", {"w:val": wval(style_np.find(qn("w:numId")), "0")}))
            insert_ordered(ppr, np, PPR_ORDER)
            return
        ilvl = np.find(qn("w:ilvl"))
        if ilvl is None:
            ilvl = make("w:ilvl")
            np.insert(0, ilvl)
        ilvl.set(qn("w:val"), str(level))

    def set_ppr(self, p, kind, level):
        new, _ = self.ref_ppr(kind, level, p)
        new = new if new is not None else make("w:pPr")
        old = p.find(qn("w:pPr"))
        if old is not None:
            mark = old.find(qn("w:rPr"))
            sect = old.find(qn("w:sectPr"))
            for e in new.findall(qn("w:rPr")):
                new.remove(e)
            if mark is not None:
                insert_ordered(new, copy.deepcopy(mark), PPR_ORDER)
            if sect is not None:
                insert_ordered(new, copy.deepcopy(sect), PPR_ORDER)
        if self.suggest:
            change = self.rev("w:pPrChange")
            inner = make("w:pPr")
            if old is not None:
                for c in elements(old):
                    if local(c) not in ("rPr", "sectPr", "pPrChange"):
                        inner.append(copy.deepcopy(c))
            change.append(inner)
            insert_ordered(new, change, PPR_ORDER)
        if old is not None:
            p.replace(old, new)
        else:
            p.insert(0, new)

    # ---- runs ----
    def template_rpr(self, segs: list[Seg]):
        src = next((s for s in segs if s.rpr is not None and not s.link), None)
        if src is None:
            return None
        rpr = copy.deepcopy(src.rpr)
        for tag in ("w:b", "w:bCs", "w:i", "w:iCs", "w:strike", "w:dstrike", "w:rPrChange", "w:ins", "w:del"):
            for e in rpr.findall(qn(tag)):
                rpr.remove(e)
        return rpr

    def make_rpr(self, template, seg: Seg):
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
    def make_run(text, rpr, deleted=False):
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

    def hyperlink(self, url, link_el):
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

    def build(self, stream, template):
        """Turn a (token, segment, change) stream into runs, hyperlinks, and revision marks."""
        groups: list[list] = []
        for text, seg, change in stream:
            if change == "del" and not self.suggest:
                continue
            key = (
                change,
                seg.link,
                seg.fmt if change == "ins" else id(seg.rpr),
                id(seg.link_el) if change != "ins" else None,
            )
            if groups and groups[-1][0] == key:
                groups[-1][1].append(text)
            else:
                groups.append([key, [text], seg, change])
        runs = []
        for _, texts, seg, change in groups:
            if change == "ins":
                rpr = self.make_rpr(template, seg)
            else:
                rpr = copy.deepcopy(seg.rpr) if seg.rpr is not None else None
            runs.append(
                (
                    change,
                    seg.link,
                    seg.link_el if change != "ins" else None,
                    self.make_run("".join(texts), rpr, change == "del"),
                )
            )
        holder = make("w:p")
        k = 0
        while k < len(runs):
            link = runs[k][1]
            group = []
            while k < len(runs) and runs[k][1] == link:
                group.append(runs[k])
                k += 1
            container = holder
            if link:
                link_el = next((g[2] for g in group if g[2] is not None), None)
                container = self.hyperlink(link, link_el)
                holder.append(container)
            for change, _, _, r in group:
                if self.suggest and change in ("ins", "del"):
                    last = container[-1] if len(container) else None
                    if last is not None and local(last) == change:
                        last.append(r)
                    else:
                        w = self.rev(f"w:{change}")
                        w.append(r)
                        container.append(w)
                else:
                    container.append(r)
        _merge_runs(holder)
        for h in holder.findall(qn("w:hyperlink")):
            _merge_runs(h)
        return list(holder)

    def rewrite(self, p, content: str):
        old_segs, _, _ = self.reader.segments(p)
        new_segs = parse_inline(content)
        old = [(t, s) for s in old_segs for t in _tokens(s.text)]
        new = [(t, s) for s in new_segs for t in _tokens(s.text)]
        lead, trail = [], []
        while old and not old[0][0].strip() and old[0][0] != "\n" and not (new and new[0][0] == old[0][0]):
            lead.append(old.pop(0))
        while old and not old[-1][0].strip() and old[-1][0] != "\n" and not (new and new[-1][0] == old[-1][0]):
            trail.insert(0, old.pop())

        def key(x):
            return (x[0], x[1].fmt, x[1].link)

        sm = SequenceMatcher(None, [key(x) for x in old], [key(x) for x in new], autojunk=False)
        stream = [(t, s, "eq") for t, s in lead]
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                stream += [(t, s, "eq") for t, s in old[i1:i2]]
            else:
                stream += [(t, s, "del") for t, s in old[i1:i2]]
                stream += [(t, s, "ins") for t, s in new[j1:j2]]
        stream += [(t, s, "eq") for t, s in trail]

        keep_start = list(p.iter(qn("w:commentRangeStart"), qn("w:bookmarkStart")))
        keep_end = list(p.iter(qn("w:commentRangeEnd"), qn("w:bookmarkEnd")))
        keep_end += [e.getparent() for e in p.iter(qn("w:commentReference"))]
        template = self.template_rpr(old_segs)
        nodes = self.build(stream, template)
        for c in elements(p):
            if local(c) != "pPr":
                p.remove(c)
        for e in keep_start + nodes + keep_end:
            p.append(e)

    # ---- tables ----
    def make_table(self, md: str):
        rows = []
        for line in md.split("\n"):
            s = line.strip()
            if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", s):
                continue
            s = s.removeprefix("|")
            s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
            rows.append([c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)])
        ncols = max((len(r) for r in rows), default=1)
        tbl = make("w:tbl")
        existing = self.body.find(f"{qn('w:tbl')}/{qn('w:tblPr')}")
        if existing is not None:
            tblpr = copy.deepcopy(existing)
        else:
            tblpr = make("w:tblPr")
            sid = self.reader.styles.id_for_name("Table Grid")
            if sid:
                tblpr.append(make("w:tblStyle", {"w:val": sid}))
            tblpr.append(make("w:tblW", {"w:w": "0", "w:type": "auto"}))
        tbl.append(tblpr)
        grid = make("w:tblGrid")
        width = str(9000 // max(ncols, 1))
        for _ in range(ncols):
            grid.append(make("w:gridCol", {"w:w": width}))
        tbl.append(grid)
        for ri, row in enumerate(rows):
            tr = make("w:tr")
            trpr = make("w:trPr")
            if ri == 0:
                trpr.append(make("w:tblHeader"))
            if self.suggest:
                trpr.append(self.rev("w:ins"))
            if len(trpr):
                tr.append(trpr)
            for ci in range(ncols):
                tc = make("w:tc")
                tcpr = make("w:tcPr")
                tcpr.append(make("w:tcW", {"w:w": width, "w:type": "dxa"}))
                tc.append(tcpr)
                text = row[ci] if ci < len(row) else ""
                p = make("w:p")
                stream = [(t, s, "ins") for s in parse_inline(text) for t in _tokens(s.text)]
                for node in self.build(stream, None):
                    p.append(node)
                tc.append(p)
                tr.append(tc)
            tbl.append(tr)
        return tbl

    # ---- comments ----
    def _comments_root(self):
        part = part_by_reltype(self.doc.part, RT_COMMENTS)
        return part_xml(part) if part is not None else None

    def _ext_root(self):
        if self._ext is None:
            part = part_by_reltype(self.doc.part, RT_COMMENTS_EXT)
            if part is None:
                xml = (
                    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    b'<w15:commentsEx xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                    b'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"/>'
                )
                partname = PackURI("/word/commentsExtended.xml")
                part = Part(partname, CT_COMMENTS_EXT, xml, self.doc.part.package)
                self.doc.part.relate_to(part, RT_COMMENTS_EXT)
            el = getattr(part, "_element", None)
            if el is not None:
                self._ext = (part, el, False)
            else:
                self._ext = (part, etree.fromstring(part.blob), True)
        return self._ext[1]

    def _comment_el(self, cid):
        root = self._comments_root()
        if root is None:
            return None
        for c in root.findall(qn("w:comment")):
            if c.get(qn("w:id")) == str(cid):
                return c
        return None

    @staticmethod
    def _para_id(comment_el):
        paras = comment_el.findall(qn("w:p"))
        if not paras:
            p = make("w:p")
            comment_el.append(p)
            paras = [p]
        pid = paras[-1].get(qn("w14:paraId"))
        if not pid:
            pid = new_para_id()
            paras[-1].set(qn("w14:paraId"), pid)
        return pid

    def _ext_entry(self, para_id, parent=None):
        root = self._ext_root()
        for ex in root.findall(qn("w15:commentEx")):
            if ex.get(qn("w15:paraId")) == para_id:
                return ex
        ex = etree.SubElement(root, qn("w15:commentEx"))
        ex.set(qn("w15:paraId"), para_id)
        if parent:
            ex.set(qn("w15:paraIdParent"), parent)
        ex.set(qn("w15:done"), "0")
        return ex

    def _ref_run(self, cid):
        r = make("w:r")
        sid = self.reader.styles.id_for_name("annotation reference")
        if sid:
            rpr = make("w:rPr")
            rpr.append(make("w:rStyle", {"w:val": sid}))
            r.append(rpr)
        r.append(make("w:commentReference", {"w:id": str(cid)}))
        return r

    def add_comment(self, target, c: PItem):
        if not c.text:
            return
        p = target if local(target) == "p" else next(target.iter(qn("w:p")), None)
        if p is None:
            self.report.warnings.append(f"Could not place comment: {_snippet(c.text)}")
            return
        parent_el = self._comment_el(c.re) if c.re is not None else None
        if c.re is not None and parent_el is None:
            self.report.warnings.append(f"Reply target re:{c.re} not found; added as a new comment.")
        comment = self.doc.comments.add_comment(text=c.text, author=self.author, initials=self.initials)
        cid = comment.comment_id
        cel = comment._comment_elm
        start = make("w:commentRangeStart", {"w:id": str(cid)})
        end = make("w:commentRangeEnd", {"w:id": str(cid)})
        ref = self._ref_run(cid)
        if parent_el is not None:
            pstart = next(
                (e for e in self.body.iter(qn("w:commentRangeStart")) if e.get(qn("w:id")) == str(c.re)), None
            )
            pend = next((e for e in self.body.iter(qn("w:commentRangeEnd")) if e.get(qn("w:id")) == str(c.re)), None)
            pref = next(
                (e.getparent() for e in self.body.iter(qn("w:commentReference")) if e.get(qn("w:id")) == str(c.re)),
                None,
            )
            if pstart is not None and pend is not None and pref is not None:
                # Word orders comments by reference position; a reply must follow its parent.
                pstart.addnext(start)
                pend.addnext(end)
                last = pref
                while True:
                    nxt = last.getnext()
                    if nxt is None or local(nxt) != "r" or nxt.find(qn("w:commentReference")) is None:
                        break
                    last = nxt
                last.addnext(ref)
            else:
                self._anchor_para(p, start, end, ref)
            parent_pid = self._para_id(parent_el)
            self._ext_entry(parent_pid)
            self._ext_entry(self._para_id(cel), parent=parent_pid)
            self.report.replies += 1
        else:
            self._anchor_para(p, start, end, ref)
            self._ext_entry(self._para_id(cel))
            self.report.comments += 1

    @staticmethod
    def _anchor_para(p, start, end, ref):
        ppr = p.find(qn("w:pPr"))
        if ppr is not None:
            ppr.addnext(start)
        else:
            p.insert(0, start)
        p.append(end)
        p.append(ref)

    def set_done(self, cid, done: bool):
        cel = self._comment_el(cid)
        if cel is None:
            return
        ex = self._ext_entry(self._para_id(cel))
        ex.set(qn("w15:done"), "1" if done else "0")
        self.report.resolved += 1


def _mergeable(r):
    return local(r) == "r" and all(local(c) in ("rPr", "t") for c in elements(r)) and r.find(qn("w:t")) is not None


def _merge_runs(parent):
    """Join adjacent plain-text runs that share identical formatting."""
    prev = None
    for r in list(elements(parent)):
        if prev is not None and _mergeable(prev) and _mergeable(r):
            a, b = prev.find(qn("w:rPr")), r.find(qn("w:rPr"))
            same = (a is None and b is None) or (
                a is not None and b is not None and etree.tostring(a, method="c14n") == etree.tostring(b, method="c14n")
            )
            if same:
                prev.findall(qn("w:t"))[-1].text += "".join(t.text or "" for t in r.findall(qn("w:t")))
                parent.remove(r)
                continue
        prev = r


def apply_note(base_docx: bytes, base_items: list[Item], new_items: list[PItem], **kw) -> tuple[bytes, Report]:
    p = Patcher(base_docx, base_items, **kw)
    out = p.apply(new_items)
    return out, p.report
