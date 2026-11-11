"""Word backend: use the signed-in Word app to read and edit cloud documents.

Word is already trusted by the tenant, so this needs no Graph consent. Pulls open the document
read-only and save a local copy. Pushes open it for editing and replay each change through Word's
scripting interface, so co-authoring, version history, and tracked changes work as in Word.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .graph import GraphError
from .inline import Seg, parse_inline, plain
from .mdparse import PItem
from .ooxml import elements
from .patch import PARA_KINDS, Report, pair_hunk, tokens
from .reader import (
    Item,
    Reader,
    join_items,
    load_document,
    read_comments,
    read_items,
)

WORD = "word"
TMP = Path.home() / "Documents" / ".spsync-word"
RS, FS, GS = "\x1e", "\x1f", "\x1d"


class WordError(GraphError):
    def __init__(self, message: str, status: int = 500, code: str = "word"):
        super().__init__(status, code, message)


# ---------------------------------------------------------------- AppleScript plumbing


def lit(s: str, newline: int = 11) -> str:
    """An AppleScript expression for `s`. `\\n` becomes a manual line break by default."""
    parts: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            parts.append('"' + "".join(buf) + '"')
            buf.clear()

    for ch in s:
        o = ord(ch)
        if ch == '"':
            buf.append('\\"')
        elif ch == "\\":
            buf.append("\\\\")
        elif ch == "\n":
            flush()
            parts.append(f"(character id {newline})")
        elif o < 32:
            flush()
            parts.append(f"(character id {o})")
        else:
            buf.append(ch)
    flush()
    return " & ".join(parts) if parts else '""'


def osa(script: str, timeout: int = 600) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False, encoding="utf-8") as f:
        f.write(script)
        path = f.name
    try:
        p = subprocess.run(["osascript", path], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise WordError("Word did not respond in time.") from exc
    finally:
        Path(path).unlink(missing_ok=True)
    if p.returncode != 0:
        raise WordError(p.stderr.strip() or "AppleScript failed")
    out = p.stdout
    return out.removesuffix("\n")


def find_doc(url: str) -> str:
    return f"""
  set d to missing value
  repeat with i from 1 to (count of documents)
    if (full name of document i) is {lit(url)} then
      set d to document i
      exit repeat
    end if
  end repeat
  if d is missing value then error "spsync: the document is not open in Word"
"""


def open_docs() -> list[tuple[str, bool]]:
    out = osa(
        """tell application "Microsoft Word"
  set out to ""
  repeat with i from 1 to (count of documents)
    set out to out & (full name of document i) & (character id 31) & (read only of document i) & (character id 30)
  end repeat
  return out
end tell"""
    )
    docs = []
    for rec in out.split(RS):
        if FS in rec:
            name, ro = rec.split(FS, 1)
            docs.append((name, ro.strip() == "true"))
    return docs


def _same(a: str, b: str) -> bool:
    return unquote(a).rstrip("/").lower() == unquote(b).rstrip("/").lower()


def link_name(url: str) -> str | None:
    u = urlparse(url)
    name = (parse_qs(u.query).get("file") or [None])[0]
    if not name:
        last = unquote(u.path.rsplit("/", 1)[-1])
        name = last or None
    return name


def open_url(url: str, edit: bool, timeout: int = 120) -> tuple[str, bool]:
    """Open `url` in Word. Returns (Word's canonical URL, read_only)."""
    before = {n for n, _ in open_docs()}
    mode = "ofe" if edit else "ofv"
    target = quote(url, safe=":/?&=%#~+,;@!$'()*")
    subprocess.run(["open", f"ms-word:{mode}|u|{target}"], check=False)
    name = link_name(url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            docs = open_docs()
        except WordError:
            continue
        for n, ro in docs:
            if _same(n, url.split("?")[0]) or (n not in before and n.startswith("http")):
                time.sleep(2)  # let Word finish loading content
                return n, ro
        if name:
            for n, ro in docs:
                if n.startswith("http") and unquote(n).rsplit("/", 1)[-1].lower() == name.lower():
                    time.sleep(2)
                    return n, ro
    raise WordError(
        "Word didn't open the document. Check the link opens in Word, and that Word is signed in.", 404, "notFound"
    )


def close_doc(url: str, save: bool = False):
    osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  close d saving {"yes" if save else "no"}
end tell"""
    )


def save_copy(url: str) -> bytes:
    """Save the open document as a local copy (which closes it in Word) and return the bytes."""
    TMP.mkdir(parents=True, exist_ok=True)
    dest = TMP / f"copy-{hashlib.sha1((url + str(time.time())).encode()).hexdigest()[:10]}.docx"
    osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  save as d file name {lit(str(dest))} file format format document
  repeat with i from 1 to (count of documents)
    if (name of document i) is {lit(dest.name)} then
      close document i saving no
      exit repeat
    end if
  end repeat
end tell"""
    )
    data = dest.read_bytes()
    dest.unlink(missing_ok=True)
    return data


def recent_files() -> list[tuple[str, str]]:
    out = osa(
        """tell application "Microsoft Word"
  set out to ""
  repeat with i from 1 to (count of recent files)
    set out to out & (path of recent file i) & (character id 31) & (name of recent file i) & (character id 30)
  end repeat
  return out
end tell"""
    )
    files = []
    for rec in out.split(RS):
        if FS in rec:
            folder, name = rec.split(FS, 1)
            if folder.startswith("http") and name.lower().endswith(".docx"):
                files.append((folder.rstrip("/") + "/" + name, name))
    return files


def inspect(url: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Paragraph texts and (author, text) for every comment, in document order."""
    out = osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  set out to ""
  repeat with i from 1 to (count of paragraphs of d)
    set out to out & (content of text object of paragraph i of d) & (character id 30)
  end repeat
  set out to out & (character id 29)
  repeat with i from 1 to (count of Word comments of d)
    set c to Word comment i of d
    set out to out & (author of c) & (character id 31) & (content of comment text of c) & (character id 30)
  end repeat
  return out
end tell"""
    )
    paras_s, _, comments_s = out.partition(GS)
    paras = paras_s.split(RS)[:-1]
    comments = []
    for rec in comments_s.split(RS):
        if FS in rec:
            a, t = rec.split(FS, 1)
            comments.append((a, t))
    return paras, comments


# ---------------------------------------------------------------- planning (pure Python)


def word_raw(p: str) -> str:
    """Word paragraph content without its paragraph or cell mark; line breaks as \\n."""
    return p.rstrip("\r\x07").replace("\x0b", "\n")


def norm(s: str) -> str:
    import re

    s = re.sub(r"‹[^›]*›", "", s)
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 32)
    return " ".join(s.split())


def offset_map(base: str, word: str) -> list[int]:
    """Map each offset in `base` (0..len) to an offset in `word`."""
    m = [0] * (len(base) + 1)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, word, autojunk=False).get_opcodes():
        for k in range(i1, i2 + 1):
            m[k] = j1 + (k - i1) if tag == "equal" else (j1 if k < i2 else j2)
    m[len(base)] = len(word)
    return m


def align(base_texts: list[str], word_texts: list[str]) -> list[int | None]:
    """Order-preserving match of base paragraphs to Word paragraph indices (0-based)."""
    bn = [norm(t) for t in base_texts]
    wn = [norm(word_raw(t)) for t in word_texts]
    out: list[int | None] = [None] * len(bn)
    sm = SequenceMatcher(None, bn, wn, autojunk=False)
    prev_b = prev_w = 0
    for b0, w0, size in sm.get_matching_blocks():
        # Fuzzy-match leftovers in the gap (for paragraphs with images or fields).
        j = prev_w
        for i in range(prev_b, b0):
            best, best_j = 0.0, None
            for k in range(j, w0):
                r = SequenceMatcher(None, bn[i], wn[k], autojunk=False).ratio()
                if r > best:
                    best, best_j = r, k
            if best_j is not None and best >= 0.6:
                out[i] = best_j
                j = best_j + 1
        for k in range(size):
            out[b0 + k] = w0 + k
        prev_b, prev_w = b0 + size, w0 + size
    return out


def unique_context(text: str, a: int, b: int, limit: int = 240) -> tuple[int, int]:
    """Grow [a, b) by whole tokens until text[a:b] occurs once in `text`."""
    toks = [(m.start(), m.end()) for m in __import__("re").finditer(r"\w+|\s+|[^\w\s]", text)]
    lo, hi = a, b
    while True:
        s = text[lo:hi]
        if s and text.count(s) == 1 or hi - lo >= limit or (lo == 0 and hi == len(text)):
            return lo, hi
        before = [t for t in toks if t[1] <= lo]
        after = [t for t in toks if t[0] >= hi]
        if before:
            lo = before[-1][0]
        if after:
            hi = after[0][1]
        if not before and not after:
            return lo, hi


def find_escape(s: str) -> str:
    return s.replace("^", "^^").replace("\n", "^l").replace("\t", "^t")


STYLE = {
    "h1": "style heading1",
    "h2": "style heading2",
    "h3": "style heading3",
    "h4": "style heading4",
    "h5": "style heading5",
    "h6": "style heading6",
    "p": "style normal",
    "quote": "style quote",
}


def style_enum(kind: str, level: int) -> str:
    if kind in ("ul", "ol"):
        base = "style list bullet" if kind == "ul" else "style list number"
        return base + (str(min(level + 1, 5)) if level else "")
    return STYLE.get(kind, "style normal")


@dataclass
class Plan:
    script: list[str] = field(default_factory=list)
    report: Report = field(default_factory=Report)


class Planner:
    def __init__(
        self, base_docx: bytes, base_items: list[Item], word_paras: list[str], word_comments: list[tuple[str, str]]
    ):
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
            if b.kind in PARA_KINDS:
                self.segs[k] = self.reader.segments(self.children[b.i])[0]
                para_idx.append(k)
        mapped = align([plain(self.segs[k]) for k in para_idx], word_paras)
        self.wp: dict[int, int] = {k: w for k, w in zip(para_idx, mapped) if w is not None}
        self.n = 0

    # Paragraph text in Word must still match what was pulled, or the note is stale.
    def check_fresh(self):
        for k, seg in self.segs.items():
            b = self.blocks[k]
            w = self.wp.get(k)
            if w is None:
                if not b.locked:
                    raise WordError("The document changed since your last pull.", 412, "preconditionFailed")
                continue
            if not b.locked and norm(plain(seg)) != norm(word_raw(self.word[w])):
                raise WordError("The document changed since your last pull.", 412, "preconditionFailed")

    def _op(self, body: str, label: str) -> str:
        self.n += 1
        return f"""
  try
{body}
  on error e
    set errs to errs & {lit(label)} & ": " & e & (character id 10)
  end try"""

    # ---- inline formatting
    @staticmethod
    def _fmt_ops(start_expr: str, segs: list[Seg], neighbor: tuple, allow_false: bool) -> list[str]:
        ops = []
        off = 0
        for s in segs:
            ln = len(s.text)
            if ln and s.text.strip():
                rng = f"(create range d start ({start_expr} + {off}) end ({start_expr} + {off + ln}))"
                for attr, want, have in (("bold", s.b, neighbor[0]), ("italic", s.i, neighbor[1])):
                    if want != have and (want or allow_false):
                        ops.append(f"    set {attr} of {rng} to {'true' if want else 'false'}")
                if s.s != neighbor[2] and (s.s or allow_false):
                    ops.append(f"    set strike through of font object of {rng} to {'true' if s.s else 'false'}")
                if s.link:
                    ops.append(
                        f"    try\n      make new hyperlink object at d with properties {{text object:{rng}, hyperlink address:{lit(s.link)}}}\n    end try"
                    )
            off += ln
        return ops

    def modify_text(self, k: int, new: PItem) -> list[str]:
        w = self.wp[k]
        old_segs = self.segs[k]
        old_text = plain(old_segs)
        new_segs = parse_inline(new.content)
        raw = word_raw(self.word[w])
        omap = offset_map(old_text, raw)
        old, pos = [], 0
        for s in old_segs:
            for t in tokens(s.text):
                old.append((t, s, pos))
                pos += len(t)
        newt = [(t, s) for s in new_segs for t in tokens(s.text)]

        def key(x):
            return (x[0], x[1].fmt, x[1].link)

        sm = SequenceMatcher(None, [key(x) for x in old], [key(x) for x in newt], autojunk=False)
        spans = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            a = old[i1][2] if i1 < len(old) else len(old_text)
            b = old[i2 - 1][2] + len(old[i2 - 1][0]) if i2 > i1 else a
            ins: list[Seg] = []
            for t, s in newt[j1:j2]:
                if ins and ins[-1].fmt == s.fmt and ins[-1].link == s.link:
                    ins[-1] = Seg(ins[-1].text + t, s.b, s.i, s.s, s.link)
                else:
                    ins.append(Seg(t, s.b, s.i, s.s, s.link))
            near = old[i1 - 1][1] if i1 > 0 else (old[i2][1] if i2 < len(old) else Seg(""))
            spans.append((a, b, ins, near))
        P = w + 1
        ops = []
        for a, b, ins, near in reversed(spans):
            wa, wb = omap[a], omap[b]
            new_text = plain(ins)
            if wa < wb:
                check = f"my same((get content of (create range d start (ps + {wa}) end (ps + {wb}))) as string, {lit(raw[wa:wb])})"
            elif wa > 0:
                ctx = max(0, wa - 12)
                check = f"my same((get content of (create range d start (ps + {ctx}) end (ps + {wa}))) as string, {lit(raw[ctx:wa])})"
            else:
                check = "true"
            ca, cb = unique_context(old_text, a, b)
            ctx_old = old_text[ca:cb]
            ctx_new = old_text[ca:a] + new_text + old_text[b:cb]
            fallback = (
                f"      set fr to text object of paragraph {P} of d\n"
                f"      set found to execute find (find object of fr) find text {lit(find_escape(ctx_old), 10)} "
                f"replace with {lit(find_escape(ctx_new), 10)} replace replace one match case true wrap find find stop\n"
                f'      if found is false then error "could not find the text to change"'
            )
            if not ctx_old or len(ctx_old) > 250:
                fallback = '      error "text in Word did not match"'
            fmt = self._fmt_ops(f"ps + {wa}", ins, near.fmt, allow_false=True)
            body = (
                f"    set ps to start of content of (text object of paragraph {P} of d)\n"
                f"    set ok to false\n"
                f"    set ok to {check}\n"
                f"    if ok then\n"
                f"      set content of (create range d start (ps + {wa}) end (ps + {wb})) to {lit(new_text)}\n"
                + "\n".join("  " + o for o in fmt)
                + f"\n    else\n{fallback}\n    end if"
            )
            ops.append(self._op(body, f"edit in “{_snip(new.md)}”"))
        return ops

    def para_scope(self, P: str) -> str:
        return (
            f"    set pr to text object of paragraph {P} of d\n"
            f"    set sc to pr\n"
            f"    if (end of content of pr) - (start of content of pr) > 1 then set sc to create range d start (start of content of pr) end ((end of content of pr) - 1)\n"
        )

    def comment_op(self, P: str, text: str) -> str:
        body = (
            self.para_scope(P)
            + f"    make new Word comment at d with properties {{comment text:{lit(text, 13)}, scope:sc}}"
        )
        return self._op(body, f"comment “{_snip(text)}”")

    def insert_op(self, new: PItem, where: str, P: int, inherit: tuple | None) -> list[str]:
        """Insert `new` after (or before) Word paragraph P (1-based)."""
        if new.kind == "table":
            rows = []
            for line in new.md.split("\n"):
                s = line.strip().strip("|")
                if set(s.replace("|", "").replace(":", "").strip()) <= {"-", " "}:
                    continue
                rows.append("\t".join(c.strip() for c in s.split("|")))
            segs = [Seg("\r".join(rows))]
            kind, level = "p", 0
        elif new.kind == "code":
            segs = [Seg(new.content.replace("\n", "\r"))]
            kind, level = "p", 0
        else:
            segs = parse_inline(new.content)
            kind, level = new.kind, new.level
        text = plain(segs)
        if where == "after":
            make = (
                f"    set pr to text object of paragraph {P} of d\n"
                f"    set pe to end of content of pr\n"
                f"    insert paragraph at (create range d start (pe - 1) end (pe - 1))\n"
                f"    set np to {P + 1}\n"
            )
        else:
            make = (
                f"    set qs to start of content of (text object of paragraph {P} of d)\n"
                f"    insert paragraph at (create range d start qs end qs)\n"
                f"    set np to {P}\n"
            )
        body = make + (
            "    set ns to start of content of (text object of paragraph np of d)\n"
            f"    set content of (create range d start ns end ns) to {lit(text, 11).replace('(character id 13)', '(character id 13)')}\n"
        )
        if inherit != (kind, level):
            body += f"    set style of (text object of paragraph np of d) to {style_enum(kind, level)}\n"
            if kind not in ("ul", "ol"):
                body += "    try\n      remove numbers (text object of paragraph np of d)\n    end try\n"
        rng = f"(create range d start ns end (ns + {len(text)}))"
        if new.kind == "code":
            body += f'    set name of font object of {rng} to "Consolas"\n'
        if new.kind == "table":
            body += f"    try\n      convert to table {rng} separator separate by tabs\n    end try\n"
        body += "\n".join(self._fmt_ops("ns", segs, (False, False, False), allow_false=False))
        return [self._op(body, f"add “{_snip(new.md)}”")]

    def delete_op(self, P: int, md: str) -> str:
        body = f'    set content of (text object of paragraph {P} of d) to ""'
        return self._op(body, f"remove “{_snip(md)}”")

    def style_op(self, P: int, kind: str, level: int, md: str) -> str:
        body = f"    set style of (text object of paragraph {P} of d) to {style_enum(kind, level)}"
        if kind not in ("ul", "ol"):
            body += f"\n    try\n      remove numbers (text object of paragraph {P} of d)\n    end try"
        return self._op(body, f"restyle “{_snip(md)}”")

    # ---- whole-note plan
    def plan(self, new_items: list[PItem]) -> Plan:
        plan = Plan()
        rep = plan.report
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

        base = self.blocks
        new_of: dict[int, int] = {}  # new block -> base block
        mods: dict[int, int] = {}  # base block -> new block
        deletes: set[int] = set()
        inserts: dict[int, list[int]] = {}  # base block anchor (-1 = start) -> new blocks
        sm = SequenceMatcher(None, [b.md for b in base], [b.md for b in new_blocks], autojunk=False)
        anchor = -1
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    new_of[j1 + k] = i1 + k
                anchor = i2 - 1
                continue
            for op in pair_hunk(base[i1:i2], new_blocks[j1:j2]):
                if op[0] == "mod":
                    bi, nj = i1 + op[1], j1 + op[2]
                    b, n = base[bi], new_blocks[nj]
                    if b.locked:
                        rep.warnings.append(
                            f"Skipped edit to a block Obsidian can't safely change ({b.lock_reason}): {_snip(b.md)}"
                        )
                        new_of[nj] = bi
                    elif b.kind in PARA_KINDS and n.kind in PARA_KINDS:
                        mods[bi] = nj
                        new_of[nj] = bi
                    else:
                        deletes.add(bi)
                        inserts.setdefault(bi, []).append(nj)
                    anchor = bi
                elif op[0] == "del":
                    deletes.add(i1 + op[1])
                    anchor = i1 + op[1]
                else:
                    inserts.setdefault(anchor, []).append(j1 + op[1])

        comments_on: dict[int, list[str]] = {}  # new block -> comment texts
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

        # Replies first: they refer to comments by position, which later edits can shift.
        if replies:
            plan.script += self.reply_ops(replies, rep)

        def wpara(bi):
            w = self.wp.get(bi)
            return None if w is None else w + 1

        # Walk base blocks bottom-up so Word paragraph numbers stay valid.
        last_para = max((wpara(k) for k in self.wp), default=None)
        for bi in range(len(base) - 1, -2, -1):
            ins = inserts.get(bi, [])
            P = wpara(bi) if bi >= 0 else None
            if ins:
                if P is not None:
                    where, at, inherit = "after", P, (base[bi].kind, base[bi].level)
                else:
                    nxt = next((k for k in range(bi + 1, len(base)) if wpara(k) is not None), None)
                    prv = next((k for k in range(bi - 1, -1, -1) if wpara(k) is not None), None) if bi >= 0 else None
                    if nxt is not None and (prv is None or nxt == bi + 1):
                        where, at, inherit = "before", wpara(nxt), (base[nxt].kind, base[nxt].level)
                    elif prv is not None:
                        where, at, inherit = "after", wpara(prv), (base[prv].kind, base[prv].level)
                    elif last_para is not None:
                        where, at, inherit = "after", last_para, None
                    else:
                        rep.warnings.append("Could not find where to add new text in Word.")
                        continue
                for nj in reversed(ins):
                    n = new_blocks[nj]
                    if n.kind == "raw":
                        rep.private_skipped += 1
                        continue
                    target = at + 1 if where == "after" else at
                    plan.script += self.insert_op(n, where, at, inherit)
                    for text in reversed(comments_on.get(nj, [])):
                        plan.script.append(self.comment_op(str(target), text))
                        rep.comments += 1
                    rep.inserted += 1
            if bi < 0:
                continue
            if P is None:
                if bi in mods or bi in deletes:
                    rep.warnings.append(f"Could not find this paragraph in Word: {_snip(base[bi].md)}")
                continue
            if bi in mods:
                n = new_blocks[mods[bi]]
                b = base[bi]
                text_ops = self.modify_text(bi, n)
                plan.script += text_ops
                if (b.kind, b.level) != (n.kind, n.level):
                    plan.script.append(self.style_op(P, n.kind, n.level, n.md))
                if text_ops or (b.kind, b.level) != (n.kind, n.level):
                    rep.modified += 1
            nj_here = [nj for nj, bb in new_of.items() if bb == bi]
            for nj in nj_here:
                for text in comments_on.get(nj, []):
                    plan.script.append(self.comment_op(str(P), text))
                    rep.comments += 1
            if bi in deletes:
                if base[bi].locked:
                    rep.warnings.append(
                        f"Skipped removing a block Obsidian can't safely change ({base[bi].lock_reason}): {_snip(base[bi].md)}"
                    )
                elif base[bi].kind in PARA_KINDS:
                    plan.script.append(self.delete_op(P, base[bi].md))
                    rep.deleted += 1
                else:
                    rep.warnings.append(
                        f"Removing tables and other objects isn't supported in Word mode: {_snip(base[bi].md)}"
                    )
        return plan

    def reply_ops(self, replies, rep) -> list[str]:
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
                rep.warnings.append(f"Couldn't find comment {parent} in Word; reply not sent: {_snip(text)}")
                continue
            body = (
                f"    set pc to Word comment {j} of d\n"
                f"    make new Word comment at d with properties {{comment text:{lit('Re ' + (authors.get(parent) or 'comment') + ': ' + text, 13)}, scope:(scope of pc)}}"
            )
            ops.append(self._op(body, f"reply “{_snip(text)}”"))
            rep.replies += 1
        if ops:
            rep.warnings.append(
                "Word can't be scripted to thread replies; replies were added as comments starting with “Re <name>:”."
            )
        return ops

    def _comment_order(self, comments):
        """Base comments in document order (by where their reference mark appears)."""
        from .ooxml import qn

        pos = {}
        for n, e in enumerate(self.doc.element.body.iter(qn("w:commentReference"))):
            pos.setdefault(int(e.get(qn("w:id"))), n)
        return sorted(comments, key=lambda c: pos.get(c.id, 10**9))


def _snip(s: str) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= 50 else s[:47] + "..."


SAME = """on same(a, b)
  considering case
    return a is b
  end considering
end same
"""


def build_script(url: str, ops: list[str], suggest: bool) -> str:
    return (
        SAME
        + f"""tell application "Microsoft Word"
{find_doc(url)}
  set errs to ""
  set oldTrack to track revisions of d
  set track revisions of d to {"true" if suggest else "false"}
{"".join(ops)}
  set track revisions of d to oldTrack
  save d
  return errs
end tell"""
    )


# ---------------------------------------------------------------- backend


def md_tag(data: bytes) -> str:
    return hashlib.sha1(join_items(read_items(data)).encode()).hexdigest()


class WordBackend:
    def __init__(self):
        self._cache: dict[str, tuple[float, bytes]] = {}

    def _info(self, url: str, data: bytes) -> dict:
        return {
            "id": url,
            "name": unquote(url.split("?")[0].rsplit("/", 1)[-1]),
            "eTag": md_tag(data),
            "webUrl": url,
            "parentReference": {"driveId": WORD},
            "file": {},
        }

    def _guard_not_editing(self, url: str):
        for n, ro in open_docs():
            if _same(n, url):
                if not ro:
                    raise WordError(
                        "The document is open for editing in Word. Close it there first.", 423, "resourceLocked"
                    )
                close_doc(n)

    def fetch(self, url: str) -> tuple[str, bytes]:
        self._guard_not_editing(url)
        name, _ = open_url(url, edit=False)
        data = save_copy(name)
        self._cache[name] = (time.time(), data)
        return name, data

    def resolve(self, ref: str) -> dict:
        name, data = self.fetch(ref)
        return self._info(name, data)

    def download(self, drive_id: str, item_id: str) -> bytes:
        hit = self._cache.get(item_id)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
        return self.fetch(item_id)[1]

    def item(self, drive_id: str, item_id: str) -> dict:
        return self._info(item_id, self.download(drive_id, item_id))

    def upload(self, *a, **kw):
        raise WordError("Word documents are updated through Word; use push.", 400, "unsupported")

    def create(self, *a, **kw):
        raise WordError("Create new documents in a OneDrive-synced folder instead.", 400, "unsupported")

    def recent(self) -> list[dict]:
        out = []
        for url, name in recent_files():
            out.append(
                {
                    "id": url,
                    "name": name,
                    "webUrl": url,
                    "parentReference": {"driveId": WORD},
                    "lastModifiedBy": {"user": {"displayName": "recent in Word"}},
                }
            )
        return out

    def search(self, query: str, size: int = 25) -> list[dict]:
        terms = [t.lower() for t in query.split()]
        return [h for h in self.recent() if all(t in h["name"].lower() for t in terms)][:size]

    def apply(
        self,
        url: str,
        base_docx: bytes,
        base_items: list[Item],
        new_items: list[PItem],
        *,
        suggest: bool,
        dry_run: bool,
    ) -> tuple[Report, bytes | None]:
        self._guard_not_editing(url)
        name, ro = open_url(url, edit=True)
        try:
            if ro:
                raise WordError("You only have view access to this document.", 403, "accessDenied")
            paras, comments = inspect(name)
            planner = Planner(base_docx, base_items, paras, comments)
            planner.check_fresh()
            plan = planner.plan(new_items)
            if dry_run or not plan.script:
                close_doc(name)
                return plan.report, None
            errs = osa(build_script(name, plan.script, suggest))
            for line in errs.splitlines():
                if line.strip():
                    plan.report.warnings.append("Word: " + line.strip())
            time.sleep(4)
            data = save_copy(name)
        except Exception:
            try:
                close_doc(name)
            except WordError:
                pass
            raise
        self._cache[name] = (time.time(), data)
        return plan.report, data
