"""Comments and their reply threads, read from the comments and commentsExtended parts."""

from __future__ import annotations

from dataclasses import dataclass

from docx.document import Document as DocxDocument

from ..ooxml import RT_COMMENTS, RT_COMMENTS_EXT, int_attr, qn
from .parts import is_on_attr, part_by_reltype, part_xml

DATE_CHARS = len("YYYY-MM-DD")


@dataclass
class CommentInfo:
    id: int
    author: str
    date: str
    text: str
    parent: int | None = None
    done: bool = False
    para_id: str | None = None


def read_comments(doc: DocxDocument) -> dict[int, CommentInfo]:
    """Comments by id. commentsExtended links a reply to its parent through the paragraph ids."""
    part = part_by_reltype(doc.part, RT_COMMENTS)
    if part is None:
        return {}
    root = part_xml(part)
    out: dict[int, CommentInfo] = {}
    by_para: dict[str, int] = {}
    for c in root.findall(qn("w:comment")):
        cid = int_attr(c, "w:id")
        paras = c.findall(qn("w:p"))
        lines = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in paras]
        para_id = paras[-1].get(qn("w14:paraId")) if paras else None
        out[cid] = CommentInfo(
            id=cid,
            author=c.get(qn("w:author"), "") or "",
            date=(c.get(qn("w:date")) or "")[:DATE_CHARS],
            text="\n".join(lines).strip(),
            para_id=para_id,
        )
        if para_id:
            by_para[para_id] = cid
    ext = part_by_reltype(doc.part, RT_COMMENTS_EXT)
    if ext is not None:
        for ex in part_xml(ext).findall(qn("w15:commentEx")):
            cid = by_para.get(ex.get(qn("w15:paraId")) or "")
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
