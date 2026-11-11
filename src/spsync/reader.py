"""Read a .docx into a block model and render it as Obsidian Markdown."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field

from docx import Document
from lxml import etree

from .inline import Seg, escape_block_start, render_inline
from .ooxml import (
    NS,
    RT_COMMENTS,
    RT_COMMENTS_EXT,
    RT_NUMBERING,
    W,
    elements,
    is_on,
    local,
    ns_of,
    qn,
    wval,
)

RAW_SDT = "%% spsync: content control (for example a table of contents). Edit it in Word. %%"


@dataclass
class Block:
    kind: str  # h1..h6, ul, ol, p, quote, code, table, raw
    level: int
    md: str
    locked: bool = False
    lock_reason: str = ""
    body_index: int | None = None
    comment_ids: list[int] = field(default_factory=list)


@dataclass
class CommentInfo:
    id: int
    author: str
    date: str
    text: str
    parent: int | None = None
    done: bool = False
    para_id: str | None = None


def load_document(data: bytes):
    return Document(io.BytesIO(data))


def part_by_reltype(part, reltype):
    for rel in part.rels.values():
        if rel.reltype == reltype and not rel.is_external:
            return rel.target_part
    return None


def part_xml(part):
    """Return the root element of a part, whether python-docx parsed it or kept a blob."""
    el = getattr(part, "_element", None)
    if el is not None:
        return el
    return etree.fromstring(part.blob)


class Styles:
    def __init__(self, doc):
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

    def numpr(self, sid: str | None):
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


def is_on_attr(v):
    return v is not None and v.lower() in ("1", "true", "on")


class Numbering:
    def __init__(self, doc):
        part = part_by_reltype(doc.part, RT_NUMBERING)
        self.root = part_xml(part) if part is not None else None

    def fmt(self, num_id: str, ilvl: int) -> str:
        if self.root is None:
            return "decimal"
        num = None
        for n in self.root.findall(qn("w:num")):
            if n.get(qn("w:numId")) == num_id:
                num = n
                break
        if num is None:
            return "decimal"
        for ov in num.findall(qn("w:lvlOverride")):
            if ov.get(qn("w:ilvl")) == str(ilvl):
                lvl = ov.find(qn("w:lvl"))
                if lvl is not None and lvl.find(qn("w:numFmt")) is not None:
                    return wval(lvl.find(qn("w:numFmt")), "decimal")
        abs_id = wval(num.find(qn("w:abstractNumId")))
        for a in self.root.findall(qn("w:abstractNum")):
            if a.get(qn("w:abstractNumId")) == abs_id:
                for lvl in a.findall(qn("w:lvl")):
                    if lvl.get(qn("w:ilvl")) == str(ilvl):
                        return wval(lvl.find(qn("w:numFmt")), "decimal")
        return "decimal"


class Reader:
    def __init__(self, doc):
        self.doc = doc
        self.styles = Styles(doc)
        self.numbering = Numbering(doc)
        self.rels = doc.part.rels
        self.media: dict[str, bytes] = {}

    # ---- paragraph classification ----
    def para_style_id(self, p) -> str | None:
        return wval(p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")) or self.styles.default_para

    def num_info(self, p):
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

    def para_kind(self, p) -> tuple[str, int]:
        name = self.styles.name(self.para_style_id(p)).lower()
        m = re.fullmatch(r"heading (\d)", name)
        if m:
            return f"h{min(max(int(m.group(1)), 1), 6)}", 0
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
    def segments(self, p):
        """Return (segments, lock reasons, comment ids) for a paragraph."""
        segs: list[Seg] = []
        locks: list[str] = []
        cids: list[int] = []
        self._walk(p, None, None, segs, locks, cids, None)
        return segs, locks, cids

    def _link_url(self, h):
        rid = h.get(qn("r:id"))
        if rid and rid in self.rels:
            url = self.rels[rid].target_ref
            anchor = h.get(qn("w:anchor"))
            return url + ("#" + anchor if anchor else "")
        anchor = h.get(qn("w:anchor"))
        return "#" + anchor if anchor else None

    def _walk(self, container, link, link_el, segs, locks, cids, rev):
        for ch in elements(container):
            name = local(ch)
            if ns_of(ch) != W:
                locks.append("embedded object")
                segs.append(Seg("‹object›", link=link))
                continue
            if name == "r":
                self._run(ch, link, link_el, segs, locks, cids, rev)
            elif name == "hyperlink":
                self._walk(ch, self._link_url(ch), ch, segs, locks, cids, rev)
            elif name == "commentRangeStart":
                cids.append(int(ch.get(qn("w:id"))))
            elif name in ("pPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd", "commentRangeEnd"):
                continue
            elif name in ("ins", "moveTo"):
                locks.append("tracked changes")
                self._walk(ch, link, link_el, segs, locks, cids, "ins")
            elif name in ("del", "moveFrom"):
                locks.append("tracked changes")
                self._walk(ch, link, link_el, segs, locks, cids, "del")
            elif name in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd"):
                locks.append("tracked changes")
            elif name in ("smartTag", "customXml", "fldSimple", "dir", "bdo"):
                locks.append(name)
                self._walk(ch, link, link_el, segs, locks, cids, rev)
            elif name == "sdt":
                locks.append("content control")
                content = ch.find(qn("w:sdtContent"))
                if content is not None:
                    self._walk(content, link, link_el, segs, locks, cids, rev)
            else:
                locks.append(name)
                segs.append(Seg(f"‹{name}›", link=link))

    def _run(self, r, link, link_el, segs, locks, cids, rev=None):
        rpr = r.find(qn("w:rPr"))
        b = i = s = False
        if rpr is not None:
            b = is_on(rpr.find(qn("w:b")))
            i = is_on(rpr.find(qn("w:i")))
            s = is_on(rpr.find(qn("w:strike"))) or is_on(rpr.find(qn("w:dstrike")))

        def add(text):
            segs.append(Seg(text, b, i, s, link, rpr=rpr, link_el=link_el, rev=rev))

        for c in elements(r):
            name = local(c)
            if ns_of(c) != W:
                locks.append("embedded object")
                add("‹object›")
            elif name == "t":
                add(c.text or "")
            elif name == "tab":
                add("\t")
            elif name == "br":
                if c.get(qn("w:type")) in ("page", "column"):
                    locks.append("page break")
                else:
                    add("\n")
            elif name == "cr":
                add("\n")
            elif name == "noBreakHyphen":
                add("-")
            elif name == "commentReference":
                cid = int(c.get(qn("w:id")))
                if cid not in cids:
                    cids.append(cid)
            elif name == "delText":
                if rev == "del":
                    add(c.text or "")
            elif name in ("rPr", "lastRenderedPageBreak", "annotationRef", "softHyphen"):
                continue
            elif name in ("fldChar", "instrText", "delInstrText"):
                locks.append("field")
            elif name in ("drawing", "pict", "object"):
                locks.append("image")
                embeds = [self.image(rid) for rid in self._image_rids(c)]
                embeds = [e for e in embeds if e]
                if embeds:
                    segs.append(Seg("‹image›", link=link, rpr=rpr, raw=" ".join(f"![[{e}]]" for e in embeds)))
                else:
                    add("‹image›")
            elif name in ("footnoteReference", "endnoteReference"):
                locks.append("footnote")
                add("‹footnote›")
            else:
                locks.append(name)
                add(f"‹{name}›")

    @staticmethod
    def _image_rids(el) -> list[str]:
        rids = []
        a_blip = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
        v_img = "{urn:schemas-microsoft-com:vml}imagedata"
        for e in el.iter(a_blip, v_img):
            rid = e.get(qn("r:embed")) or e.get(qn("r:id"))
            if rid and rid not in rids:
                rids.append(rid)
        return rids[:1]  # the first blip is the main picture; later ones are fallbacks or effects

    def image(self, rid: str) -> str | None:
        """Register an embedded picture and return its vault file name."""
        import hashlib
        import posixpath

        rel = self.rels.get(rid)
        if rel is None or rel.is_external:
            return None
        part = rel.target_part
        ext = posixpath.splitext(str(part.partname))[1].lower() or ".bin"
        if ext in (".emf", ".wmf"):
            return None  # Obsidian can't display Windows metafiles
        blob = part.blob
        name = f"spsync-{hashlib.sha1(blob).hexdigest()[:12]}{ext}"
        self.media[name] = blob
        return name

    def para_block(self, p) -> Block | None:
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

    def table_block(self, tbl) -> Block:
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
            r = r + [""] * (width - len(r))
            lines.append("| " + " | ".join(r) + " |")
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


def read_comments(doc) -> dict[int, CommentInfo]:
    part = part_by_reltype(doc.part, RT_COMMENTS)
    if part is None:
        return {}
    root = part_xml(part)
    out: dict[int, CommentInfo] = {}
    by_para: dict[str, int] = {}
    for c in root.findall(qn("w:comment")):
        cid = int(c.get(qn("w:id")))
        paras = c.findall(qn("w:p"))
        lines = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in paras]
        para_id = paras[-1].get(qn("w14:paraId")) if paras else None
        out[cid] = CommentInfo(
            id=cid,
            author=c.get(qn("w:author"), "") or "",
            date=(c.get(qn("w:date")) or "")[:10],
            text="\n".join(lines).strip(),
            para_id=para_id,
        )
        if para_id:
            by_para[para_id] = cid
    ext = part_by_reltype(doc.part, RT_COMMENTS_EXT)
    if ext is not None:
        for ex in part_xml(ext).findall(qn("w15:commentEx")):
            cid = by_para.get(ex.get(qn("w15:paraId")))
            if cid is None:
                continue
            out[cid].done = is_on_attr(ex.get(qn("w15:done")))
            parent = by_para.get(ex.get(qn("w15:paraIdParent")) or "")
            if parent is not None and parent != cid:
                out[cid].parent = parent
    return out


def comment_callout(c: CommentInfo) -> str:
    kind = "reply" if c.parent is not None else "comment"
    fold = "-" if c.done else ""
    meta = [c.author or "unknown", c.date] if c.date else [c.author or "unknown"]
    if c.done:
        meta.append("resolved")
    meta.append(f"id:{c.id}")
    if c.parent is not None:
        meta.append(f"re:{c.parent}")
    lines = [f"> [!{kind}]{fold} " + " · ".join(meta)]
    for line in (c.text or "(empty)").split("\n"):
        lines.append("> " + line if line else ">")
    return "\n".join(lines)


@dataclass
class Item:
    """One unit of the Markdown body: a content block or a comment callout."""

    t: str  # block | comment
    md: str
    kind: str = ""
    level: int = 0
    locked: bool = False
    lock_reason: str = ""
    i: int | None = None  # body child index for blocks
    id: int | None = None  # comment id
    done: bool = False

    def to_json(self):
        return {k: v for k, v in asdict(self).items() if not (v is None or v == "" or v is False) or k in ("t", "md")}

    @classmethod
    def from_json(cls, d):
        return cls(**d)


def read_items(data: bytes) -> list[Item]:
    return read_items_and_media(data)[0]


def read_items_and_media(data: bytes) -> tuple[list[Item], dict[str, bytes]]:
    doc = load_document(data)
    reader = Reader(doc)
    return items_from_doc(doc, reader), reader.media


def items_from_doc(doc, reader: Reader | None = None) -> list[Item]:
    reader = reader or Reader(doc)
    comments = read_comments(doc)
    blocks: list[Block] = []
    pending: list[int] = []
    for idx, child in enumerate(elements(doc.element.body)):
        name = local(child) if ns_of(child) == W else ""
        if name == "p":
            blk = reader.para_block(child)
        elif name == "tbl":
            blk = reader.table_block(child)
        elif name == "sectPr":
            continue
        elif name == "sdt":
            blk = Block(kind="raw", level=0, md=RAW_SDT, locked=True, lock_reason="content control")
            blk.comment_ids = [int(c.get(qn("w:id"))) for c in child.iter(qn("w:commentRangeStart"))]
        else:
            continue
        blk.body_index = idx
        if blk.kind == "empty":
            pending.extend(blk.comment_ids)
            continue
        blk.comment_ids = pending + [c for c in blk.comment_ids if c not in pending]
        pending = []
        blocks.append(blk)
    if pending and blocks:
        blocks[-1].comment_ids.extend(pending)

    placed: set[int] = set()
    children: dict[int, list[int]] = {}
    for c in comments.values():
        if c.parent is not None and c.parent in comments:
            children.setdefault(c.parent, []).append(c.id)

    def thread(cid: int) -> list[Item]:
        out = []
        if cid in placed or cid not in comments:
            return out
        placed.add(cid)
        c = comments[cid]
        out.append(Item(t="comment", md=comment_callout(c), id=cid, done=c.done))
        for child in sorted(children.get(cid, [])):
            out.extend(thread(child))
        return out

    items: list[Item] = []
    for blk in blocks:
        items.append(
            Item(
                t="block",
                md=blk.md,
                kind=blk.kind,
                level=blk.level,
                locked=blk.locked,
                lock_reason=blk.lock_reason,
                i=blk.body_index,
            )
        )
        for cid in blk.comment_ids:
            c = comments.get(cid)
            root = cid
            while c is not None and c.parent is not None and c.parent in comments:
                root = c.parent
                c = comments[root]
            items.extend(thread(root))
    leftovers = [cid for cid in sorted(comments) if cid not in placed and comments[cid].parent not in comments]
    for cid in leftovers:
        items.extend(thread(cid))
    return items


def join_items(items) -> str:
    """Join item Markdown. Adjacent list items share a list; everything else gets a blank line."""
    out: list[str] = []
    prev = None
    for it in items:
        if out:
            tight = (
                prev is not None
                and prev.t == "block"
                and it.t == "block"
                and prev.kind in ("ul", "ol")
                and it.kind in ("ul", "ol")
            )
            out.append("\n" if tight else "\n\n")
        out.append(it.md)
        prev = it
    return "".join(out) + "\n"


__all__ = ["NS", "Item", "Reader", "items_from_doc", "join_items", "read_items"]
