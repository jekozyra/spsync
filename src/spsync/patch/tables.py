"""New tables from Markdown pipe tables."""

from __future__ import annotations

import copy
import re

from lxml import etree

from ..inline import parse_inline
from ..ooxml import make, qn
from .diff import tokens
from .runs import RunBuilder

TABLE_WIDTH_TWIPS = 9000
_DIVIDER = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?")


def table_rows(md: str) -> list[list[str]]:
    """Cell text for each row, without the divider row. `\\|` is a literal pipe inside a cell."""
    rows = []
    for line in md.split("\n"):
        s = line.strip()
        if _DIVIDER.fullmatch(s):
            continue
        s = s.removeprefix("|")
        s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
        rows.append([c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)])
    return rows


def _table_props(body: etree._Element, runs: RunBuilder) -> etree._Element:
    """Copy the first existing table's properties, or use Table Grid at automatic width."""
    existing = body.find(f"{qn('w:tbl')}/{qn('w:tblPr')}")
    if existing is not None:
        return copy.deepcopy(existing)
    tblpr = make("w:tblPr")
    sid = runs.reader.styles.id_for_name("Table Grid")
    if sid:
        tblpr.append(make("w:tblStyle", {"w:val": sid}))
    tblpr.append(make("w:tblW", {"w:w": "0", "w:type": "auto"}))
    return tblpr


def _cell(text: str, width: str, runs: RunBuilder) -> etree._Element:
    tc = make("w:tc")
    tcpr = make("w:tcPr")
    tcpr.append(make("w:tcW", {"w:w": width, "w:type": "dxa"}))
    tc.append(tcpr)
    p = make("w:p")
    stream = [(t, s, "ins") for s in parse_inline(text) for t in tokens(s.text)]
    for node in runs.build(stream, None):
        p.append(node)
    tc.append(p)
    return tc


def _row(row: list[str], ncols: int, width: str, runs: RunBuilder, *, header: bool) -> etree._Element:
    tr = make("w:tr")
    trpr = make("w:trPr")
    if header:
        trpr.append(make("w:tblHeader"))
    if runs.suggest:
        trpr.append(runs.revisions.mark("w:ins"))
    if len(trpr):
        tr.append(trpr)
    for ci in range(ncols):
        tr.append(_cell(row[ci] if ci < len(row) else "", width, runs))
    return tr


def make_table(md: str, body: etree._Element, runs: RunBuilder) -> etree._Element:
    """A w:tbl for a Markdown table. The first row is the header row. Columns share the width equally."""
    rows = table_rows(md)
    ncols = max((len(r) for r in rows), default=1)
    tbl = make("w:tbl")
    tbl.append(_table_props(body, runs))
    grid = make("w:tblGrid")
    width = str(TABLE_WIDTH_TWIPS // max(ncols, 1))
    for _ in range(ncols):
        grid.append(make("w:gridCol", {"w:w": width}))
    tbl.append(grid)
    for ri, row in enumerate(rows):
        tbl.append(_row(row, ncols, width, runs, header=ri == 0))
    return tbl
