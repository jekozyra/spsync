"""New comments, replies, and resolution changes.

```text
w:body  commentRangeStart(id) ... commentRangeEnd(id) w:r/commentReference(id)
word/comments.xml           w:comment(id) / w:p(w14:paraId)
word/commentsExtended.xml   w15:commentEx(paraId, paraIdParent, done)
```

A reply links to its parent through the paraId of the last paragraph of each comment.
"""

from __future__ import annotations

from docx.document import Document as DocxDocument
from docx.opc.packuri import PackURI
from docx.opc.part import Part, XmlPart
from lxml import etree

from ..mdparse import PItem
from ..ooxml import CT_COMMENTS_EXT, RT_COMMENTS, RT_COMMENTS_EXT, local, make, new_para_id, qn
from ..reader import Reader, part_by_reltype, part_xml
from .diff import snippet
from .report import Report

EMPTY_COMMENTS_EXT = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<w15:commentsEx xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    b'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"/>'
)
COMMENTS_EXT_PARTNAME = "/word/commentsExtended.xml"


class CommentWriter:
    def __init__(self, doc: DocxDocument, reader: Reader, report: Report, *, author: str, initials: str) -> None:
        self.doc = doc
        self.body = doc.element.body
        self.reader = reader
        self.report = report
        self.author = author
        self.initials = initials
        # (part, root, kept as a blob). python-docx keeps an unknown part as bytes, so save() serializes it.
        self._ext: tuple[Part, etree._Element, bool] | None = None

    def _comments_root(self) -> etree._Element | None:
        part = part_by_reltype(self.doc.part, RT_COMMENTS)
        return part_xml(part) if part is not None else None

    def _ext_root(self) -> etree._Element:
        if self._ext is None:
            part = part_by_reltype(self.doc.part, RT_COMMENTS_EXT)
            if part is None:
                partname = PackURI(COMMENTS_EXT_PARTNAME)
                part = Part(partname, CT_COMMENTS_EXT, EMPTY_COMMENTS_EXT, self.doc.part.package)
                self.doc.part.relate_to(part, RT_COMMENTS_EXT)
            if isinstance(part, XmlPart):
                self._ext = (part, part.element, False)
            else:
                self._ext = (part, etree.fromstring(part.blob), True)
        return self._ext[1]

    def save(self) -> None:
        """Write the commentsExtended changes into its part before the document is saved."""
        if self._ext is not None:
            part, root, is_blob = self._ext
            if is_blob:
                part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    def comment_el(self, cid: int) -> etree._Element | None:
        root = self._comments_root()
        if root is None:
            return None
        for c in root.findall(qn("w:comment")):
            if c.get(qn("w:id")) == str(cid):
                return c
        return None

    @staticmethod
    def _para_id(comment_el: etree._Element) -> str:
        """The paraId of a comment's last paragraph, adding the paragraph or the id when missing."""
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

    def _ext_entry(self, para_id: str, parent: str | None = None) -> etree._Element:
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

    def _ref_run(self, cid: int) -> etree._Element:
        r = make("w:r")
        sid = self.reader.styles.id_for_name("annotation reference")
        if sid:
            rpr = make("w:rPr")
            rpr.append(make("w:rStyle", {"w:val": sid}))
            r.append(rpr)
        r.append(make("w:commentReference", {"w:id": str(cid)}))
        return r

    def _find(self, tag: str, cid: int) -> etree._Element | None:
        return next((e for e in self.body.iter(qn(tag)) if e.get(qn("w:id")) == str(cid)), None)

    def _place_reply(self, parent_id: int, start: etree._Element, end: etree._Element, ref: etree._Element) -> bool:
        """Anchor a reply beside its parent's range and reference. Returns False when the parent has no anchor."""
        pstart = self._find("w:commentRangeStart", parent_id)
        pend = self._find("w:commentRangeEnd", parent_id)
        pref_mark = self._find("w:commentReference", parent_id)
        pref = pref_mark.getparent() if pref_mark is not None else None
        if pstart is None or pend is None or pref is None:
            return False
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
        return True

    def add(self, target: etree._Element, c: PItem) -> None:
        """Add a new comment, or a reply when the callout names `re:<id>`, anchored in `target`."""
        if not c.text:
            return
        p = target if local(target) == "p" else next(target.iter(qn("w:p")), None)
        if p is None:
            self.report.warnings.append(f"Could not place comment: {snippet(c.text)}")
            return
        parent_el = self.comment_el(c.re) if c.re is not None else None
        if c.re is not None and parent_el is None:
            self.report.warnings.append(f"Reply target re:{c.re} not found; added as a new comment.")
        comment = self.doc.comments.add_comment(text=c.text, author=self.author, initials=self.initials)
        cid = comment.comment_id
        cel = comment._comment_elm
        start = make("w:commentRangeStart", {"w:id": str(cid)})
        end = make("w:commentRangeEnd", {"w:id": str(cid)})
        ref = self._ref_run(cid)
        if parent_el is not None and c.re is not None:
            if not self._place_reply(c.re, start, end, ref):
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
    def _anchor_para(p: etree._Element, start: etree._Element, end: etree._Element, ref: etree._Element) -> None:
        """Anchor a comment on the whole paragraph."""
        ppr = p.find(qn("w:pPr"))
        if ppr is not None:
            ppr.addnext(start)
        else:
            p.insert(0, start)
        p.append(end)
        p.append(ref)

    def set_done(self, cid: int, *, done: bool) -> None:
        cel = self.comment_el(cid)
        if cel is None:
            return
        ex = self._ext_entry(self._para_id(cel))
        ex.set(qn("w15:done"), "1" if done else "0")
        self.report.resolved += 1
