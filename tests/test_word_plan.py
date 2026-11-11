"""Word-mode planner tests. They build AppleScript and compile it with osacompile, without running it."""

import shutil
import subprocess
from pathlib import Path

import pytest

from spsync.inline import plain
from spsync.mdparse import parse_body
from spsync.reader import Item, join_items, read_items
from spsync.word import (
    Planner,
    WordError,
    align,
    build_script,
    lit,
    offset_map,
    unique_context,
)

FIX = Path(__file__).parent / "fixtures"


def word_view(data: bytes, items: list[Item]) -> list[str]:
    """Simulate Word's paragraph list: block paragraphs plus an empty and a table cell paragraph."""
    p = Planner(data, items, [], [])
    paras = []
    for k in sorted(p.segs):
        paras.append(plain(p.segs[k]).replace("\n", "\x0b") + "\r")
        paras.append("\r")
    paras.insert(3, "A\r\x07")
    return paras


def compile_ok(script: str) -> None:
    if not shutil.which("osacompile"):
        pytest.skip("osacompile not available")
    src = Path("/tmp/spsync-test.applescript")
    src.write_text(script, encoding="utf-8")
    p = subprocess.run(
        ["osacompile", "-o", "/tmp/spsync-test.scpt", str(src)], capture_output=True, text=True, check=False
    )
    assert p.returncode == 0, p.stderr + "\n" + script


def test_lit_escapes() -> None:
    assert lit('a"b') == '"a\\"b"'
    assert lit("x\ny") == '"x" & (character id 11) & "y"'
    assert lit("") == '""'


def test_offset_map_skips_comment_marks() -> None:
    m = offset_map("hello world", "hello\x05 world")
    assert m[6] == 7 and m[11] == 12


def test_align_handles_extra_word_paragraphs() -> None:
    assert align(["One", "Two", "Three"], ["One\r", "\r", "cell\r\x07", "Two\r", "Three\r"]) == [0, 3, 4]


def test_unique_context_grows() -> None:
    text = "the cat and the dog"
    a, b = unique_context(text, 0, 3)
    assert text.count(text[a:b]) == 1


def test_plan_compiles_and_counts() -> None:
    data = (FIX / "word-saved.docx").read_bytes()
    items = read_items(data)
    md = join_items(items)
    edited = (
        md.replace("now edited", "now **boldly** revised")
        .replace("- Third bullet", "- Third bullet\n- Fourth bullet")
        .replace("### Details", "## Details")
        .replace(
            "Closing line, rewritten.",
            "Closing line, rewritten.\n\n> [!comment] New note from Obsidian\n\nA brand new paragraph.",
        )
        .replace("> Expanded it.", "> Expanded it.\n\n> [!reply] re:0\n> Another reply")
    )
    paras = word_view(data, items)
    comments = [
        ("Alice Smith", "Please expand."),
        ("Jillian Kozyra", "Expanded it."),
        ("Jillian Kozyra", "New comment from Obsidian"),
    ]
    p = Planner(data, items, paras, comments)
    p.check_fresh()
    plan = p.plan(parse_body(edited))
    rep = plan.report
    assert (rep.modified, rep.inserted, rep.comments, rep.replies) == (2, 2, 1, 1), rep
    compile_ok(build_script("https://example.com/x.docx", plan.script, suggest=True))


def test_stale_word_text_is_detected() -> None:
    data = (FIX / "word-saved.docx").read_bytes()
    items = read_items(data)
    paras = word_view(data, items)
    paras[0] = "Project plan, renamed by someone\r"
    p = Planner(data, items, paras, [])
    with pytest.raises(WordError, match="changed"):
        p.check_fresh()
