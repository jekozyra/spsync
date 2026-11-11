import io
import os
import time
from pathlib import Path
from typing import Never

import pytest
from docx import Document

from spsync.core import Session, SyncError
from spsync.local import LocalBackend, Router
from spsync.mdparse import PItem
from spsync.patch import Report
from spsync.reader import Item, load_document

Env = tuple[Session, Path, Path]


def write_docx(path: Path, paras: list[str]) -> None:
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    path.write_bytes(buf.getvalue())


def texts(path: Path) -> list[str]:
    return [p.text for p in load_document(path.read_bytes()).paragraphs if p.text]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    od = tmp_path / "OneDrive-Contoso"
    (od / "Team Site").mkdir(parents=True)
    doc = od / "Team Site" / "Budget Memo.docx"
    write_docx(doc, ["One.", "Two.", "Three."])
    router = Router("local", local=LocalBackend(roots=[od], author="Jillian Kozyra"), word=FakeWord())
    s = Session(vault, graph=router)
    return s, doc, od


class FakeWord:
    """A Word app that has no documents. Opening a link fails with the link in the message."""

    def resolve(self, ref: str) -> Never:
        raise RuntimeError(f"word:{ref}")

    def search(self, query: str, size: int = 25) -> list[dict]:
        return []

    def recent(self) -> list[dict]:
        return []

    def item(self, drive_id: str, item_id: str) -> Never:
        raise RuntimeError(f"word:{item_id}")

    def download(self, drive_id: str, item_id: str) -> Never:
        raise RuntimeError(f"word:{item_id}")

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> Never:
        raise RuntimeError(f"word:{item_id}")

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> Never:
        raise RuntimeError(f"word:{name}")

    def me(self) -> Never:
        raise RuntimeError("word:me")

    def my_drive_id(self) -> str:
        return "word"

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
        raise RuntimeError(f"word:{url}")


def bump(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_search_and_pull_by_ref(env: Env) -> None:
    s = env[0]
    hits = s.graph.search("budget")
    assert [h["name"] for h in hits] == ["Budget Memo.docx"]
    note = s.pull(f"local:{hits[0]['id']}")
    assert note.name == "Budget Memo.md" and "Two." in note.read_text()
    assert "sharepoint: file://" in note.read_text()


def test_push_writes_file_in_place(env: Env) -> None:
    s, doc, _ = env
    ino = doc.stat().st_ino
    note = s.pull(str(doc))
    note.write_text(note.read_text().replace("Two.", "Two, edited.") + "\n> [!comment] Check this\n")
    res = s.push(note)
    assert res.status == "pushed", res.message
    assert texts(doc) == ["One.", "Two, edited.", "Three."]
    assert doc.stat().st_ino == ino
    assert "[!comment] Jillian Kozyra" in note.read_text()


def test_external_change_merges(env: Env) -> None:
    s, doc, _ = env
    note = s.pull(str(doc))
    d = load_document(doc.read_bytes())
    d.paragraphs[2].runs[0].text = "Three, from a colleague."
    d.save(str(doc))
    bump(doc)
    note.write_text(note.read_text().replace("One.", "One, mine."))
    with pytest.raises(SyncError, match="changed"):
        s.push(note)
    res = s.sync(note)
    assert res.status == "merged", res.message
    assert texts(doc) == ["One, mine.", "Two.", "Three, from a colleague."]


def test_open_in_word_blocks_push(env: Env) -> None:
    s, doc, _ = env
    note = s.pull(str(doc))
    (doc.parent / ("~$" + doc.name[2:])).write_bytes(b"owner")
    note.write_text(note.read_text().replace("One.", "One!"))
    with pytest.raises(SyncError, match="open in Word"):
        s.push(note)


def test_new_doc_in_synced_folder(env: Env) -> None:
    s, _doc, od = env
    note = s.vault / "Draft.md"
    note.write_text("# Draft\n\nHello.\n")
    s.new(note, str(od / "Team Site"))
    created = od / "Team Site" / "Draft.docx"
    assert texts(created) == ["Draft", "Hello."]
    assert "spsync: local:" in note.read_text()


def test_unsynced_link_goes_to_word(env: Env) -> None:
    s = env[0]
    with pytest.raises(Exception, match="word:https://contoso.sharepoint.com/x.docx"):
        s.pull("https://contoso.sharepoint.com/x.docx")


def test_doc_aspx_link_finds_synced_copy(env: Env) -> None:
    s, doc, _ = env
    url = (
        "https://contoso-my.sharepoint.com/:w:/r/personal/b_contoso_com/_layouts/15/Doc.aspx"
        "?sourcedoc=%7B7017%7D&file=Budget%20Memo.docx&action=default"
    )
    note = s.pull(url)
    b, _ = s.binding_for(note)
    assert note.name == "Budget Memo.md" and b.item_id == str(doc.resolve())


def test_unchanged_sync_is_quiet(env: Env) -> None:
    s, doc, _ = env
    note = s.pull(str(doc))
    time.sleep(0.01)
    assert s.sync(note).status == "unchanged"
