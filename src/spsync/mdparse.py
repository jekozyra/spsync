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
            body = text[nl + 1:] if nl != -1 else ""
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
    return bool(
        HEADING.match(line) or LIST.match(line) or line.startswith((">", "|", "%%")) or FENCE.match(line)
    )


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


def parse_body(body: str) -> list[PItem]:
    lines = body.replace("\r\n", "\n").split("\n")
    items: list[PItem] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        m = FENCE.match(line)
        if m:
            fence = m.group(1)
            j = i + 1
            while j < n and not lines[j].startswith(fence):
                j += 1
            code = lines[i + 1:j]
            raw = lines[i:j + 1]
            items.append(PItem(t="block", md="\n".join(x.rstrip() for x in raw), kind="code", content="\n".join(code)))
            i = j + 1
            continue
        m = CALLOUT.match(line)
        if m:
            body_lines = []
            j = i + 1
            while j < n and lines[j].startswith(">") and not CALLOUT.match(lines[j]):
                b = lines[j][1:]
                body_lines.append((b.removeprefix(" ")).rstrip())
                j += 1
            while body_lines and not body_lines[-1]:
                body_lines.pop()
            items.append(_callout(m.group(1), m.group(2), m.group(3).strip(), body_lines))
            i = j
            continue
        if line.startswith(">"):
            raw = []
            j = i
            while j < n and lines[j].startswith(">") and not CALLOUT.match(lines[j]):
                raw.append(lines[j].rstrip())
                j += 1
            content = "\n".join(re.sub(r"^>\s?", "", x) for x in raw)
            items.append(PItem(t="block", md="\n".join(raw), kind="quote", content=content))
            i = j
            continue
        if line.startswith("%%"):
            j = i
            raw = [line]
            while not (len(raw[-1].rstrip()) >= 4 and raw[-1].rstrip().endswith("%%")) and j + 1 < n:
                j += 1
                raw.append(lines[j].rstrip())
            items.append(PItem(t="block", md="\n".join(raw), kind="raw"))
            i = j + 1
            continue
        m = HEADING.match(line)
        if m:
            items.append(PItem(t="block", md=line, kind=f"h{len(m.group(1))}", content=m.group(2).strip()))
            i += 1
            continue
        if line.startswith("|"):
            raw = []
            j = i
            while j < n and lines[j].startswith("|"):
                raw.append(lines[j].rstrip())
                j += 1
            items.append(PItem(t="block", md="\n".join(raw), kind="table"))
            i = j
            continue
        if HR.match(line):
            i += 1
            continue
        m = LIST.match(line)
        if m:
            raw = [line]
            content = [m.group(3)]
            j = i + 1
            while j < n and lines[j].strip() and lines[j][:1] in (" ", "\t") and not LIST.match(lines[j]):
                raw.append(lines[j].rstrip())
                content.append(lines[j].strip())
                j += 1
            kind = "ul" if m.group(2) in "-*+" else "ol"
            items.append(PItem(t="block", md="\n".join(raw), kind=kind, level=_level(m.group(1)), content="\n".join(content)))
            i = j
            continue
        raw = [line]
        j = i + 1
        while j < n and lines[j].strip() and not _starts_block(lines[j]) and not HR.match(lines[j]):
            raw.append(lines[j].rstrip())
            j += 1
        items.append(PItem(t="block", md="\n".join(raw), kind="p", content="\n".join(x.strip() for x in raw)))
        i = j
    return items


def parse_note(text: str) -> tuple[dict, list[PItem]]:
    fm, body = split_frontmatter(text)
    return fm, parse_body(body)
