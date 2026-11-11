"""The note's item list: body blocks in document order, each followed by the comment threads anchored in it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from docx.document import Document as DocxDocument
from lxml import etree

from ..ooxml import W, elements, int_attr, local, ns_of, qn
from .comments import CommentInfo, comment_callout, read_comments
from .paragraphs import Block, Reader
from .parts import load_document

RAW_SDT = "%% spsync: content control (for example a table of contents). Edit it in Word. %%"
LIST_KINDS = ("ul", "ol")


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

    def to_json(self) -> dict[str, str | int | bool]:
        return {k: v for k, v in asdict(self).items() if not (v is None or v == "" or v is False) or k in ("t", "md")}

    @classmethod
    def from_json(cls, d: dict) -> Item:
        return cls(**d)


def read_items(data: bytes) -> list[Item]:
    return read_items_and_media(data)[0]


def read_items_and_media(data: bytes) -> tuple[list[Item], dict[str, bytes]]:
    doc = load_document(data)
    reader = Reader(doc)
    return items_from_doc(doc, reader), reader.media


def _body_block(reader: Reader, child: etree._Element) -> Block | None:
    name = local(child) if ns_of(child) == W else ""
    if name == "p":
        return reader.para_block(child)
    if name == "tbl":
        return reader.table_block(child)
    if name == "sdt":
        blk = Block(kind="raw", level=0, md=RAW_SDT, locked=True, lock_reason="content control")
        blk.comment_ids = [int_attr(c, "w:id") for c in child.iter(qn("w:commentRangeStart"))]
        return blk
    return None


def _body_blocks(doc: DocxDocument, reader: Reader) -> list[Block]:
    """Blocks in body order. Comments anchored in an empty paragraph move to the next block."""
    blocks: list[Block] = []
    pending: list[int] = []
    for idx, child in enumerate(elements(doc.element.body)):
        blk = _body_block(reader, child)
        if blk is None:
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
    return blocks


class _Threads:
    """Places each comment thread once: the root comment, then its replies in id order."""

    def __init__(self, comments: dict[int, CommentInfo]) -> None:
        self.comments = comments
        self.placed: set[int] = set()
        self.children: dict[int, list[int]] = {}
        for c in comments.values():
            if c.parent is not None and c.parent in comments:
                self.children.setdefault(c.parent, []).append(c.id)

    def root_of(self, cid: int) -> int:
        c = self.comments.get(cid)
        root = cid
        while c is not None and c.parent is not None and c.parent in self.comments:
            root = c.parent
            c = self.comments[root]
        return root

    def thread(self, cid: int) -> list[Item]:
        if cid in self.placed or cid not in self.comments:
            return []
        self.placed.add(cid)
        c = self.comments[cid]
        out = [Item(t="comment", md=comment_callout(c), id=cid, done=c.done)]
        for child in sorted(self.children.get(cid, [])):
            out.extend(self.thread(child))
        return out

    def leftovers(self) -> list[Item]:
        """Threads whose anchors were not found in the body, in id order."""
        out: list[Item] = []
        for cid in sorted(self.comments):
            if cid not in self.placed and self.comments[cid].parent not in self.comments:
                out.extend(self.thread(cid))
        return out


def items_from_doc(doc: DocxDocument, reader: Reader | None = None) -> list[Item]:
    reader = reader or Reader(doc)
    threads = _Threads(read_comments(doc))
    items: list[Item] = []
    for blk in _body_blocks(doc, reader):
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
            items.extend(threads.thread(threads.root_of(cid)))
    items.extend(threads.leftovers())
    return items


def join_items(items: Iterable[Item]) -> str:
    """Join item Markdown. Adjacent list items share a list; everything else gets a blank line."""
    out: list[str] = []
    prev = None
    for it in items:
        if out:
            tight = (
                prev is not None
                and prev.t == "block"
                and it.t == "block"
                and prev.kind in LIST_KINDS
                and it.kind in LIST_KINDS
            )
            out.append("\n" if tight else "\n\n")
        out.append(it.md)
        prev = it
    return "".join(out) + "\n"
