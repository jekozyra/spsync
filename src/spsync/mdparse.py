"""Parse an Obsidian note back into blocks and comment callouts."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
LIST = re.compile(r"^([\t ]*)([-*+]|\d+[.)])\s+(.*)$")
CALLOUT = re.compile(r"^>\s*\[!(comment|reply|conflict)\]([+-]?)\s*(.*)$", re.IGNORECASE)
FENCE = re.compile(r"^(```|~~~)")
HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


@dataclass
class PItem:
    t: str  # block | comment | newcomment | conflict
    md: str
    kind: str = ""
    level: int = 0
    content: str = ""
    id: int | None = None
    re: int | None = None
    text: str = ""
    done: bool = False


def split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            nl = text.find("\n", end + 4)
            body = text[nl + 1 :] if nl != -1 else ""
            try:
                fm = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), body
    return {}, text


def with_frontmatter(fm: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def _level(indent: str) -> int:
    width = indent.count("\t") * 4 + indent.count(" ")
    return width // 4 if width % 4 == 0 else (width + 2) // 4


def _starts_block(line: str) -> bool:
    return bool(HEADING.match(line) or LIST.match(line) or line.startswith((">", "|", "%%")) or FENCE.match(line))


def _callout(kind: str, fold: str, header: str, body: list[str]) -> PItem:
    md_lines = [f"> [!{kind}]{fold} {header}".rstrip()] + [("> " + b) if b else ">" for b in body]
    md = "\n".join(md_lines)
    kind = kind.lower()
    if kind == "conflict":
        return PItem(t="conflict", md=md)
    tokens = [t.strip() for t in header.split("·")]
    m_id = re.search(r"\bid:(\d+)\b", header)
    if m_id:
        return PItem(t="comment", md=md, id=int(m_id.group(1)), done=any(t.lower() == "resolved" for t in tokens))
    m_re = re.search(r"\bre:(\d+)\b", header)
    title = re.sub(r"\bre:\d+\b", "", header).strip()
    text = "\n".join([title] + body if title else body).strip()
    return PItem(t="newcomment", md=md, re=int(m_re.group(1)) if m_re else None, text=text)


# A block parser takes the lines and the index of a non-blank line. It returns None when the block does not
# start there, or the parsed item (None for a horizontal rule, which has no item) and the index after the block.
Parsed = tuple[PItem | None, int]


def _fence_block(lines: list[str], i: int) -> Parsed | None:
    m = FENCE.match(lines[i].rstrip())
    if not m:
        return None
    fence = m.group(1)
    j = i + 1
    while j < len(lines) and not lines[j].startswith(fence):
        j += 1
    code = lines[i + 1 : j]
    raw = lines[i : j + 1]
    return PItem(t="block", md="\n".join(x.rstrip() for x in raw), kind="code", content="\n".join(code)), j + 1


def _callout_block(lines: list[str], i: int) -> Parsed | None:
    m = CALLOUT.match(lines[i].rstrip())
    if not m:
        return None
    body_lines = []
    j = i + 1
    while j < len(lines) and lines[j].startswith(">") and not CALLOUT.match(lines[j]):
        body_lines.append(lines[j][1:].removeprefix(" ").rstrip())
        j += 1
    while body_lines and not body_lines[-1]:
        body_lines.pop()
    return _callout(m.group(1), m.group(2), m.group(3).strip(), body_lines), j


def _quote_block(lines: list[str], i: int) -> Parsed | None:
    if not lines[i].startswith(">"):
        return None
    raw = []
    j = i
    while j < len(lines) and lines[j].startswith(">") and not CALLOUT.match(lines[j]):
        raw.append(lines[j].rstrip())
        j += 1
    content = "\n".join(re.sub(r"^>\s?", "", x) for x in raw)
    return PItem(t="block", md="\n".join(raw), kind="quote", content=content), j


def _private_block(lines: list[str], i: int) -> Parsed | None:
    """A `%% ... %%` block. The patcher never uploads it."""
    line = lines[i].rstrip()
    if not line.startswith("%%"):
        return None
    j = i
    raw = [line]
    while not (len(raw[-1].rstrip()) >= 4 and raw[-1].rstrip().endswith("%%")) and j + 1 < len(lines):
        j += 1
        raw.append(lines[j].rstrip())
    return PItem(t="block", md="\n".join(raw), kind="raw"), j + 1


def _heading_block(lines: list[str], i: int) -> Parsed | None:
    line = lines[i].rstrip()
    m = HEADING.match(line)
    if not m:
        return None
    return PItem(t="block", md=line, kind=f"h{len(m.group(1))}", content=m.group(2).strip()), i + 1


def _table_block(lines: list[str], i: int) -> Parsed | None:
    if not lines[i].startswith("|"):
        return None
    raw = []
    j = i
    while j < len(lines) and lines[j].startswith("|"):
        raw.append(lines[j].rstrip())
        j += 1
    return PItem(t="block", md="\n".join(raw), kind="table"), j


def _rule_block(lines: list[str], i: int) -> Parsed | None:
    return (None, i + 1) if HR.match(lines[i].rstrip()) else None


def _list_block(lines: list[str], i: int) -> Parsed | None:
    line = lines[i].rstrip()
    m = LIST.match(line)
    if not m:
        return None
    raw = [line]
    content = [m.group(3)]
    j = i + 1
    while j < len(lines) and lines[j].strip() and lines[j][:1] in (" ", "\t") and not LIST.match(lines[j]):
        raw.append(lines[j].rstrip())
        content.append(lines[j].strip())
        j += 1
    kind = "ul" if m.group(2) in "-*+" else "ol"
    item = PItem(t="block", md="\n".join(raw), kind=kind, level=_level(m.group(1)), content="\n".join(content))
    return item, j


def _paragraph_block(lines: list[str], i: int) -> Parsed:
    raw = [lines[i].rstrip()]
    j = i + 1
    while j < len(lines) and lines[j].strip() and not _starts_block(lines[j]) and not HR.match(lines[j]):
        raw.append(lines[j].rstrip())
        j += 1
    return PItem(t="block", md="\n".join(raw), kind="p", content="\n".join(x.strip() for x in raw)), j


# Order matters: a callout is also a quote, and a paragraph matches anything.
_BLOCK_PARSERS = (
    _fence_block,
    _callout_block,
    _quote_block,
    _private_block,
    _heading_block,
    _table_block,
    _rule_block,
    _list_block,
    _paragraph_block,
)


def parse_body(body: str) -> list[PItem]:
    lines = body.replace("\r\n", "\n").split("\n")
    items: list[PItem] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        for parse in _BLOCK_PARSERS:
            found = parse(lines, i)
            if found is not None:
                item, i = found
                if item is not None:
                    items.append(item)
                break
    return items


def parse_note(text: str) -> tuple[dict, list[PItem]]:
    fm, body = split_frontmatter(text)
    return fm, parse_body(body)
