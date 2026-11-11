"""Plan a push in Word: map note changes onto Word paragraphs and order the ops so that indices stay valid."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..inline import Seg, parse_inline, plain
from ..mdparse import PItem
from ..ooxml import elements, int_attr, qn
from ..patch import PARA_KINDS, Report, pair_hunk, tokens
from ..reader import CommentInfo, Item, Reader, load_document, read_comments
from .ops import comment_op, delete_op, fmt_ops, insert_op, op, reply_op, style_op
from .script import WordError, lit
from .text import align, find_escape, norm, offset_map, snip, unique_context, word_raw

# Characters before an insertion point that the edit checks still match in Word.
CHECK_CONTEXT_CHARS = 12
# Word's find text field rejects longer strings.
MAX_FIND_CHARS = 250
# Newline character id for find text: 10 is a line feed.
FIND_NEWLINE = 10
UNPLACED = 10**9
STALE = "The document changed since your last pull."


@dataclass
class Plan:
    script: list[str] = field(default_factory=list)
    report: Report = field(default_factory=Report)


@dataclass
class _Span:
    """One changed range [a, b) of the old paragraph text and the segments that replace it."""

    a: int
    b: int
    ins: list[Seg]
    near: Seg


@dataclass
class _Changes:
    new_of: dict[int, int] = field(default_factory=dict)  # new block -> base block
    mods: dict[int, int] = field(default_factory=dict)  # base block -> new block
    deletes: set[int] = field(default_factory=set)
    inserts: dict[int, list[int]] = field(default_factory=dict)  # base block anchor (-1 = start) -> new blocks


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


def _merged_segs(pieces: list[tuple[str, Seg]]) -> list[Seg]:
    ins: list[Seg] = []
    for t, s in pieces:
        if ins and ins[-1].fmt == s.fmt and ins[-1].link == s.link:
            ins[-1] = Seg(ins[-1].text + t, s.b, s.i, s.s, s.link)
        else:
            ins.append(Seg(t, s.b, s.i, s.s, s.link))
    return ins


def _spans(old_segs: list[Seg], new_segs: list[Seg], old_text: str) -> list[_Span]:
    """The changed ranges between the old and new paragraph, from a token diff."""
    old: list[tuple[str, Seg, int]] = []
    pos = 0
    for s in old_segs:
        for t in tokens(s.text):
            old.append((t, s, pos))
            pos += len(t)
    newt = [(t, s) for s in new_segs for t in tokens(s.text)]
    old_keys = [(t, s.fmt, s.link) for t, s, _ in old]
    new_keys = [(t, s.fmt, s.link) for t, s in newt]
    spans = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        a = old[i1][2] if i1 < len(old) else len(old_text)
        b = old[i2 - 1][2] + len(old[i2 - 1][0]) if i2 > i1 else a
        near = old[i1 - 1][1] if i1 > 0 else (old[i2][1] if i2 < len(old) else Seg(""))
        spans.append(_Span(a, b, _merged_segs(newt[j1:j2]), near))
    return spans


class Planner:
    def __init__(
        self, base_docx: bytes, base_items: list[Item], word_paras: list[str], word_comments: list[tuple[str, str]]
    ) -> None:
        self.doc = load_document(base_docx)
        self.reader = Reader(self.doc)
        self.children = elements(self.doc.element.body)
        self.blocks = [it for it in base_items if it.t == "block"]
        self.comment_done = {it.id: it.done for it in base_items if it.t == "comment"}
        self.word = word_paras
        self.word_comments = word_comments
        self.segs: dict[int, list[Seg]] = {}
        para_idx = []
        for k, b in enumerate(self.blocks):
            if b.kind in PARA_KINDS and b.i is not None:
                self.segs[k] = self.reader.segments(self.children[b.i])[0]
                para_idx.append(k)
        mapped = align([plain(self.segs[k]) for k in para_idx], word_paras)
        self.wp: dict[int, int] = {k: w for k, w in zip(para_idx, mapped, strict=True) if w is not None}

    def check_fresh(self) -> None:
        """Paragraph text in Word must still match what was pulled, or the note is stale."""
        for k, seg in self.segs.items():
            b = self.blocks[k]
            w = self.wp.get(k)
            if w is None:
                if not b.locked:
                    raise WordError(STALE, 412, "preconditionFailed")
                continue
            if not b.locked and norm(plain(seg)) != norm(word_raw(self.word[w])):
                raise WordError(STALE, 412, "preconditionFailed")

    # ---- paragraph edits
    @staticmethod
    def _span_op(P: int, raw: str, omap: list[int], old_text: str, span: _Span, md: str) -> str:
        """Replace one span in Word paragraph P. Check the text first; fall back to find and replace."""
        wa, wb = omap[span.a], omap[span.b]
        new_text = plain(span.ins)
        if wa < wb:
            check = f"my same((get content of (create range d start (ps + {wa}) end (ps + {wb}))) as string, {lit(raw[wa:wb])})"
        elif wa > 0:
            ctx = max(0, wa - CHECK_CONTEXT_CHARS)
            check = f"my same((get content of (create range d start (ps + {ctx}) end (ps + {wa}))) as string, {lit(raw[ctx:wa])})"
        else:
            check = "true"
        ca, cb = unique_context(old_text, span.a, span.b)
        ctx_old = old_text[ca:cb]
        ctx_new = old_text[ca : span.a] + new_text + old_text[span.b : cb]
        fallback = (
            f"      set fr to text object of paragraph {P} of d\n"
            f"      set found to execute find (find object of fr) find text {lit(find_escape(ctx_old), FIND_NEWLINE)} "
            f"replace with {lit(find_escape(ctx_new), FIND_NEWLINE)} replace replace one match case true wrap find find stop\n"
            f'      if found is false then error "could not find the text to change"'
        )
        if not ctx_old or len(ctx_old) > MAX_FIND_CHARS:
            fallback = '      error "text in Word did not match"'
        fmt = fmt_ops(f"ps + {wa}", span.ins, span.near.fmt, allow_false=True)
        body = (
            f"    set ps to start of content of (text object of paragraph {P} of d)\n"
            f"    set ok to false\n"
            f"    set ok to {check}\n"
            f"    if ok then\n"
            f"      set content of (create range d start (ps + {wa}) end (ps + {wb})) to {lit(new_text)}\n"
            + "\n".join("  " + o for o in fmt)
            + f"\n    else\n{fallback}\n    end if"
        )
        return op(body, f'edit in "{snip(md)}"')

    def modify_text(self, k: int, new: PItem) -> list[str]:
        """Ops that turn base block k into `new`, last span first so earlier offsets stay valid."""
        w = self.wp[k]
        old_segs = self.segs[k]
        old_text = plain(old_segs)
        raw = word_raw(self.word[w])
        omap = offset_map(old_text, raw)
        spans = _spans(old_segs, parse_inline(new.content), old_text)
        return [self._span_op(w + 1, raw, omap, old_text, span, new.md) for span in reversed(spans)]

    # ---- whole-note plan
    def _diff_blocks(self, new_blocks: list[PItem], rep: Report) -> _Changes:
        base = self.blocks
        ch = _Changes()
        sm = SequenceMatcher(None, [b.md for b in base], [b.md for b in new_blocks], autojunk=False)
        anchor = -1
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    ch.new_of[j1 + k] = i1 + k
                anchor = i2 - 1
                continue
            for hop in pair_hunk(base[i1:i2], new_blocks[j1:j2]):
                match hop:
                    case ("mod", i, j):
                        self._pair(i1 + i, j1 + j, new_blocks[j1 + j], ch, rep)
                        anchor = i1 + i
                    case ("del", i):
                        ch.deletes.add(i1 + i)
                        anchor = i1 + i
                    case (_, j):
                        ch.inserts.setdefault(anchor, []).append(j1 + j)
        return ch

    def _pair(self, bi: int, nj: int, n: PItem, ch: _Changes, rep: Report) -> None:
        """Record an edited block: a text edit, a skipped locked block, or a replacement."""
        b = self.blocks[bi]
        if b.locked:
            rep.warnings.append(f"Skipped edit to a block Obsidian can't safely change ({b.lock_reason}): {snip(b.md)}")
            ch.new_of[nj] = bi
        elif b.kind in PARA_KINDS and n.kind in PARA_KINDS:
            ch.mods[bi] = nj
            ch.new_of[nj] = bi
        else:
            ch.deletes.add(bi)
            ch.inserts.setdefault(bi, []).append(nj)

    def _comments(
        self, attach: list[tuple[int, PItem]], existing: list[PItem], rep: Report
    ) -> tuple[dict[int, list[str]], list[tuple[int, str]]]:
        """New comment texts by new block, and (parent id, text) replies."""
        comments_on: dict[int, list[str]] = {}
        replies: list[tuple[int, str]] = []
        for nb, c in attach:
            if not c.text:
                continue
            if c.re is not None:
                replies.append((c.re, c.text))
            else:
                comments_on.setdefault(max(nb, 0), []).append(c.text)
        for c in existing:
            if c.id in self.comment_done and c.done != self.comment_done[c.id]:
                rep.warnings.append("Word can't be scripted to resolve comments; resolve it in Word or the browser.")
        return comments_on, replies

    def _wpara(self, bi: int) -> int | None:
        """The 1-based Word paragraph for base block bi, or None when it was not found in Word."""
        w = self.wp.get(bi)
        return None if w is None else w + 1

    def _insert_point(self, bi: int, last_para: int | None) -> tuple[str, int, tuple[str, int] | None] | None:
        """Where to insert after base block bi: ("after" or "before", Word paragraph, kind and level to inherit)."""
        base = self.blocks
        P = self._wpara(bi) if bi >= 0 else None
        if P is not None:
            return "after", P, (base[bi].kind, base[bi].level)
        nxt = next((k for k in range(bi + 1, len(base)) if self._wpara(k) is not None), None)
        prv = next((k for k in range(bi - 1, -1, -1) if self._wpara(k) is not None), None) if bi >= 0 else None
        if nxt is not None and (prv is None or nxt == bi + 1):
            at = self._wpara(nxt)
            if at is not None:
                return "before", at, (base[nxt].kind, base[nxt].level)
        if prv is not None:
            at = self._wpara(prv)
            if at is not None:
                return "after", at, (base[prv].kind, base[prv].level)
        if last_para is not None:
            return "after", last_para, None
        return None

    @staticmethod
    def _insert_blocks(
        ins: list[int],
        point: tuple[str, int, tuple[str, int] | None],
        new_blocks: list[PItem],
        comments_on: dict[int, list[str]],
        plan: Plan,
    ) -> None:
        """Insert new blocks at one point, last first, each followed by its comments."""
        where, at, inherit = point
        rep = plan.report
        for nj in reversed(ins):
            n = new_blocks[nj]
            if n.kind == "raw":
                rep.private_skipped += 1
                continue
            target = at + 1 if where == "after" else at
            plan.script += insert_op(n, where, at, inherit)
            for text in reversed(comments_on.get(nj, [])):
                plan.script.append(comment_op(str(target), text))
                rep.comments += 1
            rep.inserted += 1

    def _modify_block(self, bi: int, P: int, n: PItem, plan: Plan) -> None:
        b = self.blocks[bi]
        text_ops = self.modify_text(bi, n)
        plan.script += text_ops
        restyled = (b.kind, b.level) != (n.kind, n.level)
        if restyled:
            plan.script.append(style_op(P, n.kind, n.level, n.md))
        if text_ops or restyled:
            plan.report.modified += 1

    def _delete_block(self, bi: int, P: int, plan: Plan) -> None:
        b = self.blocks[bi]
        rep = plan.report
        if b.locked:
            rep.warnings.append(
                f"Skipped removing a block Obsidian can't safely change ({b.lock_reason}): {snip(b.md)}"
            )
        elif b.kind in PARA_KINDS:
            plan.script.append(delete_op(P, b.md))
            rep.deleted += 1
        else:
            rep.warnings.append(f"Removing tables and other objects isn't supported in Word mode: {snip(b.md)}")

    def plan(self, new_items: list[PItem]) -> Plan:
        plan = Plan()
        rep = plan.report
        new_blocks, attach, existing = _split_items(new_items)
        ch = self._diff_blocks(new_blocks, rep)
        comments_on, replies = self._comments(attach, existing, rep)
        # Replies first: they refer to comments by position, which later edits can shift.
        if replies:
            plan.script += self.reply_ops(replies, rep)
        # Walk base blocks bottom-up so Word paragraph numbers stay valid.
        last_para = max((w + 1 for w in self.wp.values()), default=None)
        for bi in range(len(self.blocks) - 1, -2, -1):
            ins = ch.inserts.get(bi, [])
            if ins:
                point = self._insert_point(bi, last_para)
                if point is None:
                    rep.warnings.append("Could not find where to add new text in Word.")
                    continue
                self._insert_blocks(ins, point, new_blocks, comments_on, plan)
            if bi >= 0:
                self._apply_block(bi, ch, new_blocks, comments_on, plan)
        return plan

    def _apply_block(
        self, bi: int, ch: _Changes, new_blocks: list[PItem], comments_on: dict[int, list[str]], plan: Plan
    ) -> None:
        """Edit, comment on, and delete base block bi, in that order."""
        rep = plan.report
        P = self._wpara(bi)
        if P is None:
            if bi in ch.mods or bi in ch.deletes:
                rep.warnings.append(f"Could not find this paragraph in Word: {snip(self.blocks[bi].md)}")
            return
        if bi in ch.mods:
            self._modify_block(bi, P, new_blocks[ch.mods[bi]], plan)
        for nj in [nj for nj, bb in ch.new_of.items() if bb == bi]:
            for text in comments_on.get(nj, []):
                plan.script.append(comment_op(str(P), text))
                rep.comments += 1
        if bi in ch.deletes:
            self._delete_block(bi, P, plan)

    # ---- replies
    def reply_ops(self, replies: list[tuple[int, str]], rep: Report) -> list[str]:
        """Replies as new comments that quote the parent's author. Word comments are matched by author and text."""
        base_comments = sorted(read_comments(self.doc).values(), key=lambda c: c.id)
        order = self._comment_order(base_comments)
        key_b = [(c.author, norm(c.text)) for c in order]
        key_w = [(a, norm(t)) for a, t in self.word_comments]
        idx: dict[int, int] = {}
        for b0, w0, size in SequenceMatcher(None, key_b, key_w, autojunk=False).get_matching_blocks():
            for k in range(size):
                idx[order[b0 + k].id] = w0 + k + 1
        authors = {c.id: c.author for c in base_comments}
        ops = []
        for parent, text in sorted(replies, key=lambda r: -idx.get(r[0], 0)):
            j = idx.get(parent)
            if j is None:
                rep.warnings.append(f"Couldn't find comment {parent} in Word; reply not sent: {snip(text)}")
                continue
            ops.append(reply_op(j, authors.get(parent) or "comment", text))
            rep.replies += 1
        if ops:
            rep.warnings.append(
                "Word can't be scripted to thread replies; replies were added as comments starting with 'Re <name>:'."
            )
        return ops

    def _comment_order(self, comments: list[CommentInfo]) -> list[CommentInfo]:
        """Base comments in document order (by where their reference mark appears)."""
        pos: dict[int, int] = {}
        for n, e in enumerate(self.doc.element.body.iter(qn("w:commentReference"))):
            pos.setdefault(int_attr(e, "w:id"), n)
        return sorted(comments, key=lambda c: pos.get(c.id, UNPLACED))
