"""Paragraph and table blocks: classification, inline segments, lock reasons, and comment anchors.

A block is locked when it holds content that the patcher cannot rewrite, such as a field, an image, or a
pending tracked change. The note shows locked content, and the patcher skips edits to it.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass, field, replace

from docx.document import Document as DocxDocument
from lxml import etree

from ..inline import Seg, escape_block_start, render_inline
from ..ooxml import W, elements, int_attr, is_on, local, ns_of, qn, wval
from .parts import Numbering, Styles

A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
MEDIA_HASH_CHARS = 12
MAX_HEADING_LEVEL = 6
# Obsidian cannot display Windows metafiles.
UNSUPPORTED_IMAGE_EXTS = (".emf", ".wmf")

# Paragraph children that carry no visible text.
_WALK_SKIP = {"pPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd", "commentRangeEnd"}
# Tracked-change wrappers and the revision they show.
_REVISIONS = {"ins": "ins", "moveTo": "ins", "del": "del", "moveFrom": "del"}
_MOVE_RANGES = {"moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd"}
# Wrappers whose runs are shown, but which lock the paragraph.
_LOCKING_WRAPPERS = {"smartTag", "customXml", "fldSimple", "dir", "bdo"}

# Run children that carry no visible text.
_RUN_SKIP = {"rPr", "lastRenderedPageBreak", "annotationRef", "softHyphen"}
_RUN_TEXT = {"tab": "\t", "cr": "\n", "noBreakHyphen": "-"}
_RUN_FIELDS = {"fldChar", "instrText", "delInstrText"}
_RUN_IMAGES = {"drawing", "pict", "object"}
_RUN_NOTES = {"footnoteReference", "endnoteReference"}
_PAGE_BREAKS = ("page", "column")


@dataclass
class Block:
    kind: str  # h1..h6, ul, ol, p, quote, code, table, raw, empty
    level: int
    md: str
    locked: bool = False
    lock_reason: str = ""
    body_index: int | None = None
    comment_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class _Context:
    """The hyperlink and tracked change that enclose the runs being read."""

    link: str | None = None
    link_el: etree._Element | None = None
    rev: str | None = None


@dataclass
class _Collected:
    """What one paragraph yields: segments, lock reasons, and the ids of comments anchored in it."""

    segs: list[Seg] = field(default_factory=list)
    locks: list[str] = field(default_factory=list)
    cids: list[int] = field(default_factory=list)

    def placeholder(self, name: str, ctx: _Context) -> None:
        """Lock the paragraph and show `name` in place of content that the note cannot express."""
        self.locks.append(name)
        self.segs.append(Seg(f"‹{name}›", link=ctx.link))


@dataclass
class _Run:
    """One w:r element: its formatting and where its segments go."""

    ctx: _Context
    rpr: etree._Element | None
    b: bool
    i: bool
    s: bool
    out: _Collected

    def add(self, text: str) -> None:
        c = self.ctx
        self.out.segs.append(Seg(text, self.b, self.i, self.s, c.link, rpr=self.rpr, link_el=c.link_el, rev=c.rev))


def _plain_run_text(c: etree._Element, name: str, rev: str | None) -> str | None:
    """The text of a run child that only carries text, or None when the child is something else."""
    if name == "t":
        return c.text or ""
    if name in _RUN_TEXT:
        return _RUN_TEXT[name]
    if name == "br" and c.get(qn("w:type")) not in _PAGE_BREAKS:
        return "\n"
    if name == "delText" and rev == "del":
        return c.text or ""
    return None


class Reader:
    def __init__(self, doc: DocxDocument) -> None:
        self.doc = doc
        self.styles = Styles(doc)
        self.numbering = Numbering(doc)
        self.rels = doc.part.rels
        self.media: dict[str, bytes] = {}

    # ---- paragraph classification ----
    def para_style_id(self, p: etree._Element) -> str | None:
        return wval(p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")) or self.styles.default_para

    def num_info(self, p: etree._Element) -> tuple[str | None, int]:
        """The numbering id and level of a paragraph, from its own properties or its style."""
        np = p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
        if np is None:
            np = self.styles.numpr(self.para_style_id(p))
        if np is None:
            return None, 0
        num_id = wval(np.find(qn("w:numId")))
        ilvl = int(wval(np.find(qn("w:ilvl")), "0") or 0)
        if num_id in (None, "0"):
            return None, 0
        return num_id, ilvl

    def para_kind(self, p: etree._Element) -> tuple[str, int]:
        name = self.styles.name(self.para_style_id(p)).lower()
        m = re.fullmatch(r"heading (\d)", name)
        if m:
            return f"h{min(max(int(m.group(1)), 1), MAX_HEADING_LEVEL)}", 0
        if name == "title":
            return "h1", 0
        num_id, ilvl = self.num_info(p)
        styled = re.fullmatch(r"list (bullet|number)(?: (\d))?", name)
        if styled:
            level = ilvl or (int(styled.group(2)) - 1 if styled.group(2) else 0)
            return ("ul" if styled.group(1) == "bullet" else "ol"), level
        if num_id:
            fmt = self.numbering.fmt(num_id, ilvl)
            if fmt == "bullet":
                return "ul", ilvl
            if fmt != "none":
                return "ol", ilvl
        if "quote" in name:
            return "quote", 0
        return "p", 0

    # ---- inline content ----
    def segments(self, p: etree._Element) -> tuple[list[Seg], list[str], list[int]]:
        """Return (segments, lock reasons, comment ids) for a paragraph."""
        out = _Collected()
        self._walk(p, _Context(), out)
        return out.segs, out.locks, out.cids

    def _link_url(self, h: etree._Element) -> str | None:
        rid = h.get(qn("r:id"))
        anchor = h.get(qn("w:anchor"))
        if rid and rid in self.rels:
            url = self.rels[rid].target_ref
            return url + ("#" + anchor if anchor else "")
        return "#" + anchor if anchor else None

    def _walk(self, container: etree._Element, ctx: _Context, out: _Collected) -> None:
        for ch in elements(container):
            name = local(ch)
            if ns_of(ch) != W:
                out.locks.append("embedded object")
                out.segs.append(Seg("‹object›", link=ctx.link))
            elif name in _WALK_SKIP:
                continue
            elif name == "r":
                self._run(ch, ctx, out)
            elif name == "commentRangeStart":
                out.cids.append(int_attr(ch, "w:id"))
            else:
                self._walk_wrapper(ch, name, ctx, out)

    def _walk_wrapper(self, ch: etree._Element, name: str, ctx: _Context, out: _Collected) -> None:
        """An element that can wrap runs: a hyperlink, a tracked change, a smart tag, or a content control."""
        if name == "hyperlink":
            self._walk(ch, replace(ctx, link=self._link_url(ch), link_el=ch), out)
        elif name in _REVISIONS:
            out.locks.append("tracked changes")
            self._walk(ch, replace(ctx, rev=_REVISIONS[name]), out)
        elif name in _MOVE_RANGES:
            out.locks.append("tracked changes")
        elif name in _LOCKING_WRAPPERS:
            out.locks.append(name)
            self._walk(ch, ctx, out)
        elif name == "sdt":
            out.locks.append("content control")
            content = ch.find(qn("w:sdtContent"))
            if content is not None:
                self._walk(content, ctx, out)
        else:
            out.placeholder(name, ctx)

    def _run(self, r: etree._Element, ctx: _Context, out: _Collected) -> None:
        rpr = r.find(qn("w:rPr"))
        b = i = s = False
        if rpr is not None:
            b = is_on(rpr.find(qn("w:b")))
            i = is_on(rpr.find(qn("w:i")))
            s = is_on(rpr.find(qn("w:strike"))) or is_on(rpr.find(qn("w:dstrike")))
        run = _Run(ctx, rpr, b, i, s, out)
        for c in elements(r):
            if ns_of(c) != W:
                out.locks.append("embedded object")
                run.add("‹object›")
            else:
                self._run_child(c, run)

    def _run_child(self, c: etree._Element, run: _Run) -> None:
        name = local(c)
        if name in _RUN_SKIP:
            return
        text = _plain_run_text(c, name, run.ctx.rev)
        if text is not None:
            run.add(text)
        elif name in ("br", "delText"):
            # A page or column break locks the paragraph; deleted text outside a deletion is not shown.
            if name == "br":
                run.out.locks.append("page break")
        elif name == "commentReference":
            cid = int_attr(c, "w:id")
            if cid not in run.out.cids:
                run.out.cids.append(cid)
        elif name in _RUN_FIELDS:
            run.out.locks.append("field")
        elif name in _RUN_IMAGES:
            self._image_run(c, run)
        elif name in _RUN_NOTES:
            run.out.locks.append("footnote")
            run.add("‹footnote›")
        else:
            run.out.locks.append(name)
            run.add(f"‹{name}›")

    def _image_run(self, c: etree._Element, run: _Run) -> None:
        run.out.locks.append("image")
        embeds = [e for e in (self.image(rid) for rid in self._image_rids(c)) if e]
        if embeds:
            raw = " ".join(f"![[{e}]]" for e in embeds)
            run.out.segs.append(Seg("‹image›", link=run.ctx.link, rpr=run.rpr, raw=raw))
        else:
            run.add("‹image›")

    @staticmethod
    def _image_rids(el: etree._Element) -> list[str]:
        rids = []
        for e in el.iter(A_BLIP, V_IMAGEDATA):
            rid = e.get(qn("r:embed")) or e.get(qn("r:id"))
            if rid and rid not in rids:
                rids.append(rid)
        return rids[:1]  # the first blip is the main picture; later ones are fallbacks or effects

    def image(self, rid: str) -> str | None:
        """Register an embedded picture and return its vault file name."""
        rel = self.rels.get(rid)
        if rel is None or rel.is_external:
            return None
        part = rel.target_part
        ext = posixpath.splitext(str(part.partname))[1].lower() or ".bin"
        if ext in UNSUPPORTED_IMAGE_EXTS:
            return None
        blob = part.blob
        name = f"spsync-{hashlib.sha1(blob).hexdigest()[:MEDIA_HASH_CHARS]}{ext}"
        self.media[name] = blob
        return name

    def para_block(self, p: etree._Element) -> Block:
        kind, level = self.para_kind(p)
        segs, locks, cids = self.segments(p)
        text = render_inline(segs).strip()
        if not text and not locks:
            return Block(kind="empty", level=0, md="", comment_ids=cids)
        if not text:
            # Nothing visible (a page break, say). Keep a placeholder so the block round-trips.
            reason = ", ".join(sorted(set(locks)))
            return Block(kind="raw", level=0, md=f"%% {reason} %%", locked=True, lock_reason=reason, comment_ids=cids)
        return Block(
            kind=kind,
            level=level,
            md=block_line(kind, level, text),
            locked=bool(locks),
            lock_reason=", ".join(sorted(set(locks))),
            comment_ids=cids,
        )

    def table_block(self, tbl: etree._Element) -> Block:
        """A locked Markdown table. Each cell joins its paragraphs with <br>."""
        rows = []
        cids: list[int] = []
        for tr in tbl.findall(qn("w:tr")):
            cells = []
            for tc in tr.findall(qn("w:tc")):
                parts = []
                for p in tc.iter(qn("w:p")):
                    segs, _, pc = self.segments(p)
                    cids.extend(c for c in pc if c not in cids)
                    t = render_inline(segs).strip()
                    if t:
                        parts.append(t)
                cells.append("<br>".join(parts).replace("|", "\\|"))
            rows.append(cells)
        width = max((len(r) for r in rows), default=1) or 1
        lines = []
        for idx, r in enumerate(rows or [[""]]):
            padded = r + [""] * (width - len(r))
            lines.append("| " + " | ".join(padded) + " |")
            if idx == 0:
                lines.append("|" + " --- |" * width)
        return Block(kind="table", level=0, md="\n".join(lines), locked=True, lock_reason="table", comment_ids=cids)


def block_line(kind: str, level: int, text: str) -> str:
    text = escape_block_start(text)
    if kind.startswith("h"):
        return "#" * int(kind[1]) + " " + text
    if kind == "ul":
        return "\t" * level + "- " + text
    if kind == "ol":
        return "\t" * level + "1. " + text
    if kind == "quote":
        return "> " + text
    return text
