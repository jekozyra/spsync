"""The patcher: maps note blocks onto body elements and applies block, paragraph, and comment changes."""

from __future__ import annotations

import copy
import io
from difflib import SequenceMatcher

from lxml import etree

from ..inline import Seg, parse_inline
from ..mdparse import PItem
from ..ooxml import PPR_ORDER, RPR_ORDER, elements, ensure_child, insert_ordered, local, make, qn, wval
from ..reader import Item, Reader, load_document
from .comments import CommentWriter
from .diff import pair_hunk, snippet, tokens
from .report import BaseMismatchError, ConflictError, Report
from .runs import Revisions, RunBuilder, StreamEntry
from .tables import make_table

REVISION_MARKS = ("ins", "del", "moveFrom", "moveTo")
# A paragraph mark's run properties put its revision marks first.
PARA_RPR_ORDER = list(REVISION_MARKS) + [x for x in RPR_ORDER if x not in REVISION_MARKS]
PARA_KINDS = {"h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "p", "quote"}
LIST_KINDS = ("ul", "ol")
CODE_FONT = "Consolas"
DEFAULT_AUTHOR = "spsync"
BASE_MISMATCH = "Saved base document does not match its block map. Pull again."
# Body elements that each block kind can map to.
_BLOCK_ELEMENTS = {"table": ("tbl",), "raw": ("sdt", "p")}


def _split_items(new_items: list[PItem]) -> tuple[list[PItem], list[tuple[int, PItem]], list[PItem]]:
    """Blocks, new comments with the index of the block above them, and existing comments."""
    blocks: list[PItem] = []
    attach: list[tuple[int, PItem]] = []
    existing: list[PItem] = []
    for it in new_items:
        if it.t == "block":
            blocks.append(it)
        elif it.t == "newcomment":
            attach.append((len(blocks) - 1, it))
        elif it.t == "comment":
            existing.append(it)
    return blocks, attach, existing


def _target(result: list[etree._Element | None], bi: int) -> etree._Element | None:
    """The block a new comment attaches to: the nearest placed block at or above `bi`, else the first one."""
    bi = max(bi, 0)
    for k in range(min(bi, len(result) - 1), -1, -1):
        el = result[k]
        if el is not None and el.getparent() is not None:
            return el
    for el in result:
        if el is not None and el.getparent() is not None:
            return el
    return None


def _new_block_style(kind: str, level: int) -> str | None:
    """The Word style name for a new block that has no existing block of the same kind to copy."""
    if kind.startswith("h"):
        return f"heading {kind[1]}"
    suffix = f" {level + 1}" if level else ""
    return {"ul": "List Bullet" + suffix, "ol": "List Number" + suffix, "quote": "Quote"}.get(kind)


class Patcher:
    def __init__(
        self, base_docx: bytes, base_items: list[Item], *, author: str, initials: str = "", suggest: bool = False
    ) -> None:
        self.doc = load_document(base_docx)
        self.reader = Reader(self.doc)
        self.body = self.doc.element.body
        self.children = elements(self.body)
        self.base_items = base_items
        self.base_blocks = [it for it in base_items if it.t == "block"]
        self.base_comment_done = {it.id: it.done for it in base_items if it.t == "comment"}
        self.author = author or DEFAULT_AUTHOR
        self.initials = initials
        self.suggest = suggest
        self.report = Report()
        self.index_of: dict[int, int] = {}
        self.revisions = Revisions(self.body, self.author)
        self.runs = RunBuilder(self.doc, self.reader, self.revisions, suggest=suggest)
        self.comments = CommentWriter(self.doc, self.reader, self.report, author=self.author, initials=initials)
        self._check_base()

    # ---- setup ----
    def _check_base(self) -> None:
        for b in self.base_blocks:
            if b.i is None or b.i >= len(self.children):
                raise BaseMismatchError(BASE_MISMATCH)
            if local(self.children[b.i]) not in _BLOCK_ELEMENTS.get(b.kind, ("p",)):
                raise BaseMismatchError(BASE_MISMATCH)
            self.index_of[id(self.children[b.i])] = b.i

    def elem(self, b: Item) -> etree._Element:
        if b.i is None:
            raise BaseMismatchError(BASE_MISMATCH)
        return self.children[b.i]

    # ---- main entry ----
    def apply(self, new_items: list[PItem]) -> bytes:
        if any(it.t == "conflict" for it in new_items):
            raise ConflictError("The note still has [!conflict] callouts. Resolve them and delete the callouts first.")
        new_blocks, attach, existing = _split_items(new_items)
        result, to_delete = self._place_blocks(new_blocks)
        for b in to_delete:
            self.delete(b)
        for bi, c in attach:
            target = _target(result, bi)
            if target is None:
                self.report.warnings.append(f"Could not place comment: {snippet(c.text)}")
                continue
            self.comments.add(target, c)
        for c in existing:
            if c.id is not None and c.id in self.base_comment_done and c.done != self.base_comment_done[c.id]:
                self.comments.set_done(c.id, done=c.done)
        return self.save()

    def _place_blocks(self, new_blocks: list[PItem]) -> tuple[list[etree._Element | None], list[Item]]:
        """The body element for each new block, and the base blocks to delete afterward."""
        base = self.base_blocks
        sm = SequenceMatcher(None, [b.md for b in base], [b.md for b in new_blocks], autojunk=False)
        result: list[etree._Element | None] = [None] * len(new_blocks)
        anchor: etree._Element | None = None
        to_delete: list[Item] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    result[j1 + k] = self.elem(base[i1 + k])
                    anchor = result[j1 + k]
                continue
            anchor = self._apply_hunk(base[i1:i2], new_blocks, j1, j2, result, anchor, to_delete)
        return result, to_delete

    def _apply_hunk(
        self,
        old_blocks: list[Item],
        new_blocks: list[PItem],
        j1: int,
        j2: int,
        result: list[etree._Element | None],
        anchor: etree._Element | None,
        to_delete: list[Item],
    ) -> etree._Element | None:
        """Apply one replaced hunk. Returns the element that the next insertion goes after."""
        for op in pair_hunk(old_blocks, new_blocks[j1:j2]):
            match op:
                case ("mod", i, j):
                    old = old_blocks[i]
                    el = self.modify(old, new_blocks[j1 + j], to_delete)
                    result[j1 + j] = el
                    anchor = el if el is not None else self.elem(old)
                case ("del", i):
                    to_delete.append(old_blocks[i])
                    anchor = self.elem(old_blocks[i])
                case (_, j):
                    el = self.insert(new_blocks[j1 + j], anchor)
                    result[j1 + j] = el
                    if el is not None:
                        anchor = el
        return anchor

    def save(self) -> bytes:
        self.comments.save()
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()

    # ---- block operations ----
    def modify(self, old: Item, new: PItem, to_delete: list[Item]) -> etree._Element | None:
        el = self.elem(old)
        if old.locked:
            self.report.warnings.append(
                f"Skipped edit to a block Obsidian can't safely change ({old.lock_reason}): {snippet(old.md)}"
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

    def place(self, el: etree._Element, anchor: etree._Element | None) -> etree._Element:
        """Insert `el` after `anchor`, or before the first block when there is no anchor."""
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

    def insert(self, new: PItem, anchor: etree._Element | None) -> etree._Element | None:
        """Insert a new block. A private `%% ... %%` block is never inserted."""
        if new.kind == "raw":
            self.report.private_skipped += 1
            return None
        self.report.inserted += 1
        if new.kind == "table":
            return self.place(make_table(new.md, self.body, self.runs), anchor)
        if new.kind == "code":
            last = anchor
            for line in new.content.split("\n") or [""]:
                rpr = make("w:rPr")
                rpr.append(make("w:rFonts", {"w:ascii": CODE_FONT, "w:hAnsi": CODE_FONT, "w:cs": CODE_FONT}))
                p = self.new_para("p", 0, [Seg(line)], rpr_override=rpr, near=last)
                last = self.place(p, last)
            return last
        return self.place(self.new_para(new.kind, new.level, parse_inline(new.content), near=anchor), anchor)

    def new_para(
        self,
        kind: str,
        level: int,
        segs: list[Seg],
        rpr_override: etree._Element | None = None,
        near: etree._Element | None = None,
    ) -> etree._Element:
        p = make("w:p")
        ppr, ref_p = self.ref_ppr(kind, level, near)
        if ppr is not None:
            p.append(ppr)
        template = (
            rpr_override
            if rpr_override is not None
            else self.runs.template_rpr(self.reader.segments(ref_p)[0] if ref_p is not None else [])
        )
        stream = [(t, s, "ins") for s in segs for t in tokens(s.text)]
        for node in self.runs.build(stream, template):
            p.append(node)
        if self.suggest:
            ppr = p.find(qn("w:pPr"))
            if ppr is None:
                ppr = make("w:pPr")
                p.insert(0, ppr)
            mark = ensure_child(ppr, "w:rPr", PPR_ORDER)
            insert_ordered(mark, self.revisions.mark("w:ins"), PARA_RPR_ORDER)
        return p

    def delete(self, b: Item) -> None:
        el = self.elem(b)
        parent = el.getparent()
        if parent is None:
            return
        if not self.suggest:
            parent.remove(el)
            self.report.deleted += 1
            return
        if b.locked or local(el) != "p":
            self.report.warnings.append(
                f"Skipped suggested deletion of a block Obsidian can't safely change ({b.lock_reason or b.kind}): {snippet(b.md)}"
            )
            return
        self._suggest_delete(el)
        self.report.deleted += 1

    def _suggest_delete(self, el: etree._Element) -> None:
        """Mark every run and the paragraph mark as deleted. Comment references and tracked runs stay."""
        for r in list(el.iter(qn("w:r"))):
            if r.find(qn("w:commentReference")) is not None:
                continue
            rparent = r.getparent()
            if rparent is not None and local(rparent) in ("ins", "del"):
                continue
            d = self.revisions.mark("w:del")
            r.addprevious(d)
            d.append(r)
            for t in r.findall(qn("w:t")):
                t.tag = qn("w:delText")
        ppr = el.find(qn("w:pPr"))
        if ppr is None:
            ppr = make("w:pPr")
            el.insert(0, ppr)
        mark = ensure_child(ppr, "w:rPr", PPR_ORDER)
        insert_ordered(mark, self.revisions.mark("w:del"), PARA_RPR_ORDER)

    # ---- paragraph properties ----
    def _ref_block(self, kind: str, level: int, near: etree._Element | None) -> Item | None:
        """The closest unlocked base block of the same kind, preferring the same level and blocks above `near`."""
        near_idx = self.index_of.get(id(near), 0) if near is not None else 0
        cands = [b for b in self.base_blocks if b.kind == kind and not b.locked]
        same = [b for b in cands if b.level == level] or cands
        before = [b for b in same if b.i is not None and b.i <= near_idx]
        return (before[-1] if before else same[0]) if same else None

    def ref_ppr(
        self, kind: str, level: int, near: etree._Element | None
    ) -> tuple[etree._Element | None, etree._Element | None]:
        """Copy paragraph properties from the closest existing paragraph of the same kind."""
        best = self._ref_block(kind, level, near)
        if best is not None:
            ref_p = self.elem(best)
            src = ref_p.find(qn("w:pPr"))
            ppr = copy.deepcopy(src) if src is not None else make("w:pPr")
            self._clean_ppr(ppr)
            if kind in LIST_KINDS and best.level != level:
                self._set_level(ppr, level)
            return ppr, ref_p
        name = _new_block_style(kind, level)
        sid = self.reader.styles.id_for_name(name) if name else None
        if sid is None and kind in LIST_KINDS and level:
            sid = self.reader.styles.id_for_name("List Bullet" if kind == "ul" else "List Number")
        if sid is None:
            if kind in (*LIST_KINDS, "quote") or kind.startswith("h"):
                self.report.warnings.append(f"No matching Word style for new {kind} block; used body text style.")
            p_cands = [b for b in self.base_blocks if b.kind == "p" and not b.locked]
            if p_cands and kind != "p":
                return self.ref_ppr("p", 0, near)
            return None, None
        ppr = make("w:pPr")
        ppr.append(make("w:pStyle", {"w:val": sid}))
        return ppr, None

    @staticmethod
    def _clean_ppr(ppr: etree._Element) -> None:
        """Remove section breaks and revision marks from copied paragraph properties."""
        for tag in ("w:sectPr", "w:pPrChange"):
            for e in ppr.findall(qn(tag)):
                ppr.remove(e)
        mark = ppr.find(qn("w:rPr"))
        if mark is not None:
            for tag in ("w:ins", "w:del", "w:moveFrom", "w:moveTo", "w:rPrChange"):
                for e in mark.findall(qn(tag)):
                    mark.remove(e)

    def _set_level(self, ppr: etree._Element, level: int) -> None:
        np = ppr.find(qn("w:numPr"))
        if np is None:
            style_np = self.reader.styles.numpr(wval(ppr.find(qn("w:pStyle"))))
            if style_np is None:
                return
            np = make("w:numPr")
            np.append(make("w:ilvl", {"w:val": str(level)}))
            np.append(make("w:numId", {"w:val": wval(style_np.find(qn("w:numId")), "0") or "0"}))
            insert_ordered(ppr, np, PPR_ORDER)
            return
        ilvl = np.find(qn("w:ilvl"))
        if ilvl is None:
            ilvl = make("w:ilvl")
            np.insert(0, ilvl)
        ilvl.set(qn("w:val"), str(level))

    def set_ppr(self, p: etree._Element, kind: str, level: int) -> None:
        """Change a paragraph's kind or level. The paragraph mark and section break stay."""
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
            change = self.revisions.mark("w:pPrChange")
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
    @staticmethod
    def _diff_stream(old_segs: list[Seg], content: str) -> list[StreamEntry]:
        """A token stream that keeps unchanged tokens and marks the rest as deleted or inserted.

        Leading and trailing whitespace that the note dropped stays as kept text, so trimming in the note
        does not show as a deletion.
        """
        new_segs = parse_inline(content)
        old = [(t, s) for s in old_segs for t in tokens(s.text)]
        new = [(t, s) for s in new_segs for t in tokens(s.text)]
        lead, trail = [], []
        while old and not old[0][0].strip() and old[0][0] != "\n" and not (new and new[0][0] == old[0][0]):
            lead.append(old.pop(0))
        while old and not old[-1][0].strip() and old[-1][0] != "\n" and not (new and new[-1][0] == old[-1][0]):
            trail.insert(0, old.pop())

        def key(x: tuple[str, Seg]) -> tuple[str, tuple[bool, bool, bool], str | None]:
            return (x[0], x[1].fmt, x[1].link)

        sm = SequenceMatcher(None, [key(x) for x in old], [key(x) for x in new], autojunk=False)
        stream: list[StreamEntry] = [(t, s, "eq") for t, s in lead]
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                stream += [(t, s, "eq") for t, s in old[i1:i2]]
            else:
                stream += [(t, s, "del") for t, s in old[i1:i2]]
                stream += [(t, s, "ins") for t, s in new[j1:j2]]
        stream += [(t, s, "eq") for t, s in trail]
        return stream

    def rewrite(self, p: etree._Element, content: str) -> None:
        """Replace a paragraph's runs with the edited content. Comment anchors and bookmarks stay."""
        old_segs, _, _ = self.reader.segments(p)
        stream = self._diff_stream(old_segs, content)
        keep_start = list(p.iter(qn("w:commentRangeStart"), qn("w:bookmarkStart")))
        keep_end = list(p.iter(qn("w:commentRangeEnd"), qn("w:bookmarkEnd")))
        keep_end += [r for r in (e.getparent() for e in p.iter(qn("w:commentReference"))) if r is not None]
        template = self.runs.template_rpr(old_segs)
        nodes = self.runs.build(stream, template)
        for c in elements(p):
            if local(c) != "pPr":
                p.remove(c)
        for e in keep_start + nodes + keep_end:
            p.append(e)


def apply_note(
    base_docx: bytes,
    base_items: list[Item],
    new_items: list[PItem],
    *,
    author: str,
    initials: str = "",
    suggest: bool = False,
) -> tuple[bytes, Report]:
    p = Patcher(base_docx, base_items, author=author, initials=initials, suggest=suggest)
    out = p.apply(new_items)
    return out, p.report
