"""AppleScript for one change: edit, insert, delete, restyle, or comment on a Word paragraph.

Each op runs inside a `try` block, so a failed op adds a line to `errs` and the script continues.
"""

from __future__ import annotations

from ..inline import Seg, parse_inline, plain
from ..mdparse import PItem
from .script import lit
from .text import snip, style_enum

CODE_FONT = "Consolas"
NO_FORMAT = (False, False, False)
# Newline character ids for `lit`: 13 is a paragraph break, 11 is a manual line break.
PARAGRAPH_BREAK = 13
LINE_BREAK = 11


def op(body: str, label: str) -> str:
    return f"""
  try
{body}
  on error e
    set errs to errs & {lit(label)} & ": " & e & (character id 10)
  end try"""


def fmt_ops(start_expr: str, segs: list[Seg], neighbor: tuple[bool, bool, bool], *, allow_false: bool) -> list[str]:
    """Set bold, italic, strike, and links on new text that starts at `start_expr`.

    Word gives new text the formatting of its neighbor, so only differences from `neighbor` are set.
    With `allow_false`, formatting that the neighbor has and the segment lacks is turned off.
    """
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


def para_scope(P: str) -> str:
    """Set `sc` to paragraph P without its paragraph mark, the scope for a comment."""
    return (
        f"    set pr to text object of paragraph {P} of d\n"
        f"    set sc to pr\n"
        f"    if (end of content of pr) - (start of content of pr) > 1 then set sc to create range d start (start of content of pr) end ((end of content of pr) - 1)\n"
    )


def comment_op(P: str, text: str) -> str:
    body = (
        para_scope(P)
        + f"    make new Word comment at d with properties {{comment text:{lit(text, PARAGRAPH_BREAK)}, scope:sc}}"
    )
    return op(body, f'comment "{snip(text)}"')


def _insert_content(new: PItem) -> tuple[list[Seg], str, int]:
    """The segments, kind, and level for a new block. Tables and code become plain paragraphs first."""
    if new.kind == "table":
        rows = []
        for line in new.md.split("\n"):
            s = line.strip().strip("|")
            if set(s.replace("|", "").replace(":", "").strip()) <= {"-", " "}:
                continue
            rows.append("\t".join(c.strip() for c in s.split("|")))
        return [Seg("\r".join(rows))], "p", 0
    if new.kind == "code":
        return [Seg(new.content.replace("\n", "\r"))], "p", 0
    return parse_inline(new.content), new.kind, new.level


def insert_op(new: PItem, where: str, P: int, inherit: tuple[str, int] | None) -> list[str]:
    """Insert `new` after (or before) Word paragraph P (1-based)."""
    segs, kind, level = _insert_content(new)
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
        f"    set content of (create range d start ns end ns) to {lit(text, LINE_BREAK)}\n"
    )
    if inherit != (kind, level):
        body += f"    set style of (text object of paragraph np of d) to {style_enum(kind, level)}\n"
        if kind not in ("ul", "ol"):
            body += "    try\n      remove numbers (text object of paragraph np of d)\n    end try\n"
    rng = f"(create range d start ns end (ns + {len(text)}))"
    if new.kind == "code":
        body += f'    set name of font object of {rng} to "{CODE_FONT}"\n'
    if new.kind == "table":
        body += f"    try\n      convert to table {rng} separator separate by tabs\n    end try\n"
    body += "\n".join(fmt_ops("ns", segs, NO_FORMAT, allow_false=False))
    return [op(body, f'add "{snip(new.md)}"')]


def delete_op(P: int, md: str) -> str:
    body = f'    set content of (text object of paragraph {P} of d) to ""'
    return op(body, f'remove "{snip(md)}"')


def style_op(P: int, kind: str, level: int, md: str) -> str:
    body = f"    set style of (text object of paragraph {P} of d) to {style_enum(kind, level)}"
    if kind not in ("ul", "ol"):
        body += f"\n    try\n      remove numbers (text object of paragraph {P} of d)\n    end try"
    return op(body, f'restyle "{snip(md)}"')


def reply_op(j: int, author: str, text: str) -> str:
    """A reply to Word comment j (1-based), added as a new comment on the same text that names the parent's author."""
    comment = f"Re {author}: {text}"
    body = (
        f"    set pc to Word comment {j} of d\n"
        f"    make new Word comment at d with properties {{comment text:{lit(comment, PARAGRAPH_BREAK)}, scope:(scope of pc)}}"
    )
    return op(body, f'reply "{snip(text)}"')
