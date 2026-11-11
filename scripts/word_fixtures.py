"""Write patched .docx fixtures so they can be opened in real Word for validation."""

import io
import sys
from pathlib import Path

from docx import Document

from spsync.mdparse import parse_body
from spsync.patch import apply_note
from spsync.reader import join_items, read_items


def base_doc() -> bytes:
    d = Document()
    d.add_heading("Project plan", level=1)
    p = d.add_paragraph("This is ")
    p.add_run("important").bold = True
    p.add_run(" and ")
    p.add_run("subtle").italic = True
    p.add_run(" text.")
    d.add_paragraph("First bullet", style="List Bullet")
    d.add_paragraph("Second bullet", style="List Bullet")
    d.add_heading("Details", level=2)
    t = d.add_paragraph("Commented paragraph here.")
    d.add_comment(t.runs, text="Please expand.", author="Alice Smith", initials="AS")
    tbl = d.add_table(rows=2, cols=2)
    for (r, c), v in {(0, 0): "A", (0, 1): "B", (1, 0): "1", (1, 1): "2"}.items():
        tbl.cell(r, c).text = v
    d.add_paragraph("Closing line.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def main(out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = base_doc()
    (out / "0-base.docx").write_bytes(data)
    items = read_items(data)
    md = join_items(items)
    cid = next(i.id for i in items if i.t == "comment")
    edited = (
        md.replace("text.", "text, now edited with a [link](https://example.com).")
        .replace("- Second bullet", "- Second bullet\n\t- Nested bullet\n- Third bullet")
        .replace("Closing line.", "Closing line, rewritten.\n\n> [!comment] New comment from Obsidian\n\n| X | Y |\n| --- | --- |\n| new | table |")
        .replace("> Please expand.", f"> Please expand.\n\n> [!reply] re:{cid}\n> Expanded it.")
        .replace("## Details", "### Details")
    )
    for name, suggest in (("1-direct.docx", False), ("2-suggest.docx", True)):
        doc, rep = apply_note(data, items, parse_body(edited), author="Jillian Kozyra", initials="JK", suggest=suggest)
        (out / name).write_bytes(doc)
        print(name, rep.summary(), rep.warnings)
    resolved = md.replace("> [!comment] Alice Smith", "> [!comment] Alice Smith · resolved", 1)
    doc, rep = apply_note(data, items, parse_body(resolved), author="Jillian Kozyra")
    (out / "3-resolved.docx").write_bytes(doc)
    print("3-resolved.docx", rep.summary())
    d = Document()
    buf = io.BytesIO()
    d.save(buf)
    blank = buf.getvalue()
    new_md = "# Fresh doc\n\nWritten in **Obsidian**.\n\n1. one\n2. two\n\n> A quote\n\n```\ncode line\n```\n"
    doc, rep = apply_note(blank, read_items(blank), parse_body(new_md), author="Jillian Kozyra")
    (out / "4-new.docx").write_bytes(doc)
    print("4-new.docx", rep.summary(), rep.warnings)


if __name__ == "__main__":
    main(sys.argv[1])
