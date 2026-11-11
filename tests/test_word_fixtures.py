"""Regression tests against documents re-saved by Microsoft Word for Mac."""

from pathlib import Path

from lxml import etree

from spsync.mdparse import parse_body
from spsync.patch import apply_note, pair_hunk
from spsync.reader import join_items, load_document, read_items

FIX = Path(__file__).parent / "fixtures"


def body(data):
    return etree.tostring(load_document(data).element.body, method="c14n")


def test_word_doc_noop_and_threading():
    data = (FIX / "word-saved.docx").read_bytes()
    items = read_items(data)
    md = join_items(items)
    assert "[!reply]" in md and "re:0" in md
    assert [p.md for p in parse_body(md)] == [i.md for i in items]
    out, rep = apply_note(data, items, parse_body(md), author="Me")
    assert not rep.changed and body(out) == body(data)


def test_word_doc_edit_keeps_link_and_formatting():
    data = (FIX / "word-saved.docx").read_bytes()
    items = read_items(data)
    md = join_items(items).replace("now edited", "now revised")
    out, rep = apply_note(data, items, parse_body(md), author="Me")
    assert rep.modified == 1
    md2 = join_items(read_items(out))
    assert "**important** and *subtle* text, now revised with a [link](https://example.com)." in md2


def test_word_suggestions_render_as_marks():
    md = join_items(read_items((FIX / "word-suggest.docx").read_bytes()))
    assert "==Third bullet==" in md


def test_pair_hunk_prefers_similar_blocks():
    class B:
        def __init__(self, md):
            self.md = md

    ops = pair_hunk([B("## Details")], [B("\t- Nested bullet"), B("- Third"), B("### Details")])
    assert ops == [("ins", 0), ("ins", 1), ("mod", 0, 2)]
