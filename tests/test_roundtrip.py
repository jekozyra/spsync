import io

from docx import Document
from lxml import etree

from spsync.inline import Seg, parse_inline, render_inline
from spsync.mdparse import parse_body
from spsync.ooxml import NS, qn
from spsync.patch import apply_note
from spsync.reader import Item, join_items, load_document, read_items


def make_doc() -> bytes:
    d = Document()
    d.add_heading("Project plan", level=1)
    p = d.add_paragraph("This is ")
    r = p.add_run("important")
    r.bold = True
    p.add_run(" and ")
    r = p.add_run("subtle")
    r.italic = True
    p.add_run(" text with a * star and snake_case.")
    d.add_paragraph("")
    d.add_paragraph("First bullet", style="List Bullet")
    d.add_paragraph("Second bullet", style="List Bullet")
    d.add_paragraph("Step one", style="List Number")
    d.add_heading("Details", level=2)
    target = d.add_paragraph("Commented paragraph here.")
    d.add_comment(target.runs, text="Please expand.", author="Alice Smith", initials="AS")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "A"
    t.cell(0, 1).text = "B"
    t.cell(1, 0).text = "1"
    t.cell(1, 1).text = "2"
    d.add_paragraph("Closing line.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def body_xml(data: bytes) -> bytes:
    doc = load_document(data)
    return etree.tostring(doc.element.body, method="c14n")


def note_for(data: bytes) -> tuple[list[Item], str]:
    items = read_items(data)
    return items, join_items(items)


def test_inline_roundtrip() -> None:
    segs = [Seg("a "), Seg("bold", b=True), Seg(" "), Seg("both", b=True, i=True), Seg(" x*y [z] 50% snake_case _u_")]
    md = render_inline(segs)
    back = parse_inline(md)
    assert "".join(s.text for s in back) == "".join(s.text for s in segs)
    assert [s.fmt for s in back if s.text.strip() == "bold"] == [(True, False, False)]
    assert [s.fmt for s in back if s.text == "both"] == [(True, True, False)]


def test_render_shape() -> None:
    _items, md = note_for(make_doc())
    assert "# Project plan" in md
    assert "**important**" in md and "*subtle*" in md
    assert "- First bullet\n- Second bullet\n1. Step one" in md
    assert "> [!comment] Alice Smith" in md and "> Please expand." in md
    assert "| A | B |" in md


def test_parse_matches_render() -> None:
    items, md = note_for(make_doc())
    parsed = parse_body(md)
    assert [p.md for p in parsed] == [i.md for i in items]
    assert [p.t for p in parsed] == [i.t for i in items]


def test_noop_push_leaves_body_untouched() -> None:
    data = make_doc()
    items, md = note_for(data)
    out, rep = apply_note(data, items, parse_body(md), author="Me")
    assert not rep.changed
    assert body_xml(out) == body_xml(data)


def test_edit_word_preserves_formatting() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("with a", "with one")
    out, rep = apply_note(data, items, parse_body(md2), author="Me")
    assert rep.modified == 1
    _, md3 = note_for(out)
    assert "with one \\* star" in md3
    assert "**important**" in md3
    assert body_xml(out) != body_xml(data)


def test_insert_list_item_uses_list_style() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("- Second bullet", "- Second bullet\n- Third bullet")
    out, rep = apply_note(data, items, parse_body(md2), author="Me")
    assert rep.inserted == 1
    doc = load_document(out)
    p = next(p for p in doc.paragraphs if p.text == "Third bullet")
    assert p.style is not None and p.style.name == "List Bullet"


def test_delete_and_heading_change() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("Closing line.", "").replace("## Details", "### Details")
    out, _rep = apply_note(data, items, parse_body(md2), author="Me")
    doc = load_document(out)
    texts = [p.text for p in doc.paragraphs]
    assert "Closing line." not in texts
    assert [p.style.name if p.style else None for p in doc.paragraphs if p.text == "Details"] == ["Heading 3"]


def test_new_comment_and_reply() -> None:
    data = make_doc()
    items, md = note_for(data)
    cid = next(i.id for i in items if i.t == "comment")
    md2 = md.replace("Closing line.", "Closing line.\n\n> [!comment] Is this final?")
    md2 = md2.replace("> Please expand.", f"> Please expand.\n\n> [!reply] re:{cid}\n> Done, expanded.")
    out, rep = apply_note(data, items, parse_body(md2), author="Jillian", initials="JK")
    assert rep.comments == 1 and rep.replies == 1
    _items3, md3 = note_for(out)
    assert "> [!comment] Jillian" in md3 and "> Is this final?" in md3
    assert f"re:{cid}" in md3 and "> Done, expanded." in md3
    # The reply should render under its parent.
    assert md3.index("Please expand.") < md3.index("Done, expanded.") < md3.index("Closing line.")


def test_resolve_comment() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("> [!comment] Alice Smith", "> [!comment] Alice Smith · resolved", 1)
    out, rep = apply_note(data, items, parse_body(md2), author="Me")
    assert rep.resolved == 1
    _, md3 = note_for(out)
    assert "[!comment]- Alice Smith" in md3 and "resolved" in md3


def test_suggest_mode_tracks_changes() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("Closing line.", "Closing paragraph.").replace("- Second bullet", "- Second bullet\n- New bullet")
    out, _rep = apply_note(data, items, parse_body(md2), author="Me", suggest=True)
    doc = load_document(out)
    body = doc.element.body
    ins = body.findall(".//w:ins", NS)
    dels = body.findall(".//w:del", NS)
    assert ins and dels
    deltext = "".join(t.text for t in body.iter(qn("w:delText")))
    assert "line" in deltext
    # Reading back shows the proposed text, locked because of tracked changes.
    items3, md3 = note_for(out)
    assert "Closing ~~line~~==paragraph==." in md3
    assert any(i.locked and "tracked" in i.lock_reason for i in items3)


def test_locked_table_edit_is_skipped() -> None:
    data = make_doc()
    items, md = note_for(data)
    md2 = md.replace("| A | B |", "| A | C |")
    out, rep = apply_note(data, items, parse_body(md2), author="Me")
    assert rep.warnings and "table" in rep.warnings[0]
    assert body_xml(out) == body_xml(data)


def _png() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


PNG = _png()


def test_images_render_as_embeds() -> None:
    from spsync.reader import read_items_and_media

    d = Document()
    d.add_paragraph("Before the picture.")
    d.add_picture(io.BytesIO(PNG))
    d.add_paragraph("After.")
    buf = io.BytesIO()
    d.save(buf)
    data = buf.getvalue()
    items, media = read_items_and_media(data)
    md = join_items(items)
    (name,) = media
    assert f"![[{name}]]" in md and media[name] == PNG
    assert [p.md for p in parse_body(md)] == [i.md for i in items]
    out, rep = apply_note(data, items, parse_body(md.replace("After.", "After, edited.")), author="Me")
    assert rep.modified == 1 and f"![[{name}]]" in join_items(read_items(out))


def test_page_break_paragraph_round_trips() -> None:
    from docx.enum.text import WD_BREAK

    d = Document()
    d.add_paragraph("One.")
    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    d.add_paragraph("Two.")
    buf = io.BytesIO()
    d.save(buf)
    data = buf.getvalue()
    items, md = note_for(data)
    assert "%% page break %%" in md
    assert [p.md for p in parse_body(md)] == [i.md for i in items]
    out, rep = apply_note(data, items, parse_body(md), author="Me")
    assert not rep.changed and body_xml(out) == body_xml(data)


def test_create_from_blank() -> None:
    d = Document()
    buf = io.BytesIO()
    d.save(buf)
    blank = buf.getvalue()
    items = read_items(blank)
    md = "# Title\n\nHello **world** and [link](https://example.com/a%20b).\n\n- one\n\t- nested\n\n| H1 | H2 |\n| --- | --- |\n| x | y |\n\n%% private note %%\n"
    out, rep = apply_note(blank, items, parse_body(md), author="Me")
    _items2, md2 = note_for(out)
    assert "# Title" in md2
    assert "**world**" in md2
    assert "[link](https://example.com/a%20b)" in md2
    assert "\t- nested" in md2
    assert "| x | y |" in md2
    assert "private note" not in md2
    assert rep.private_skipped == 1
