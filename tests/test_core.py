import io
from collections.abc import Callable
from pathlib import Path
from typing import Never

import pytest
from docx import Document
from docx.document import Document as DocxDocument

from spsync.core import Session, SyncError
from spsync.graph import GraphError
from spsync.local import WordEditor
from spsync.reader import load_document

Env = tuple[Session, "FakeGraph", Path]


def docx_bytes(paras: list[str]) -> bytes:
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class FakeGraph:
    """An in-memory SharePoint drive that holds one document."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.version = 1
        self.uploads = 0
        self.locked = False

    def _item(self) -> dict:
        return {
            "id": "ITEM",
            "name": "Plan.docx",
            "eTag": f'"v{self.version}"',
            "webUrl": "https://contoso.sharepoint.com/sites/x/Plan.docx",
            "parentReference": {"driveId": "DRIVE"},
            "file": {},
        }

    @property
    def word(self) -> WordEditor:
        raise AssertionError("these tests do not use Word")

    def resolve(self, ref: str) -> dict:
        return self._item()

    def item(self, drive_id: str, item_id: str) -> dict:
        return self._item()

    def download(self, drive_id: str, item_id: str) -> bytes:
        return self.data

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> Never:
        raise AssertionError("these tests do not create documents")

    def search(self, query: str, size: int = 25) -> list[dict]:
        return []

    def recent(self) -> list[dict]:
        return []

    def my_drive_id(self) -> str:
        return "DRIVE"

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> dict:
        if self.locked:
            raise GraphError(423, "resourceLocked", "locked")
        if etag != self._item()["eTag"]:
            raise GraphError(412, "preconditionFailed", "etag")
        self.data = data
        self.version += 1
        self.uploads += 1
        return self._item()

    def me(self) -> dict:
        return {"displayName": "Jillian Kozyra"}

    def remote_edit(self, fn: Callable[[DocxDocument], object]) -> None:
        doc = load_document(self.data)
        fn(doc)
        buf = io.BytesIO()
        doc.save(buf)
        self.data = buf.getvalue()
        self.version += 1


@pytest.fixture
def env(tmp_path: Path) -> Env:
    (tmp_path / ".obsidian").mkdir()
    g = FakeGraph(docx_bytes(["Alpha paragraph.", "Beta paragraph.", "Gamma paragraph."]))
    s = Session(tmp_path, graph=g)
    note = s.pull("https://x")
    return s, g, note


def texts(g: FakeGraph) -> list[str]:
    return [p.text for p in load_document(g.data).paragraphs if p.text]


def test_pull_writes_note(env: Env) -> None:
    _s, _g, note = env
    text = note.read_text()
    assert note.name == "Plan.md"
    assert "spsync: DRIVE:ITEM" in text and "Alpha paragraph." in text


def test_push_roundtrip(env: Env) -> None:
    s, g, note = env
    note.write_text(note.read_text().replace("Beta paragraph.", "Beta paragraph, edited."))
    res = s.push(note)
    assert res.status == "pushed"
    assert texts(g) == ["Alpha paragraph.", "Beta paragraph, edited.", "Gamma paragraph."]
    assert s.push(note).status == "unchanged"


def test_push_refuses_stale_base(env: Env) -> None:
    s, g, note = env
    g.remote_edit(lambda d: d.add_paragraph("Remote addition."))
    note.write_text(note.read_text().replace("Alpha", "Alpha!"))
    with pytest.raises(SyncError, match="changed in SharePoint"):
        s.push(note)


def test_locked_document(env: Env) -> None:
    s, g, note = env
    g.locked = True
    note.write_text(note.read_text().replace("Alpha", "Alpha!"))
    with pytest.raises(SyncError, match="locked"):
        s.push(note)


def test_sync_pulls_remote_only(env: Env) -> None:
    s, g, note = env
    g.remote_edit(lambda d: d.add_paragraph("Remote addition."))
    assert s.sync(note).status == "pulled"
    assert "Remote addition." in note.read_text()


def test_sync_merges_disjoint_edits(env: Env) -> None:
    s, g, note = env

    def edit(d: DocxDocument) -> None:
        d.paragraphs[2].runs[0].text = "Gamma paragraph, remote."

    g.remote_edit(edit)
    note.write_text(note.read_text().replace("Alpha paragraph.", "Alpha paragraph, local."))
    res = s.sync(note)
    assert res.status == "merged", res.message
    assert texts(g) == ["Alpha paragraph, local.", "Beta paragraph.", "Gamma paragraph, remote."]
    assert "Gamma paragraph, remote." in note.read_text()


def test_adjacent_edits_merge_without_conflict() -> None:
    from spsync.core import merge_items

    md, n = merge_items(
        ["## H", "Para.", "Tail."], ["## Renamed", "Para.", "Tail."], ["## H", "Para, remote.", "Tail."]
    )
    assert n == 0 and "## Renamed" in md and "Para, remote." in md


def test_sync_conflict_then_resolve(env: Env) -> None:
    s, g, note = env

    def edit(d: DocxDocument) -> None:
        d.paragraphs[1].runs[0].text = "Beta remote."

    g.remote_edit(edit)
    note.write_text(note.read_text().replace("Beta paragraph.", "Beta local."))
    res = s.sync(note)
    assert res.status == "conflict"
    text = note.read_text()
    assert "[!conflict]" in text and "Beta local." in text and "> Beta remote." in text
    with pytest.raises(SyncError, match="conflict"):
        s.push(note)
    # Resolve: keep a combined line and drop the callout.
    start = text.index("> [!conflict]")
    end = text.index("Gamma paragraph.")
    note.write_text(text[:start] + text[end:].replace("Beta local.", "").replace("Gamma", "Gamma"))
    note.write_text(note.read_text().replace("Beta local.", "Beta merged."))
    res = s.sync(note)
    assert res.status == "pushed", res.message
    assert texts(g) == ["Alpha paragraph.", "Beta merged.", "Gamma paragraph."]


def test_new_comment_gets_id_after_push(env: Env) -> None:
    s, _g, note = env
    note.write_text(note.read_text().replace("Beta paragraph.", "Beta paragraph.\n\n> [!comment] Can we cut this?"))
    s.push(note)
    text = note.read_text()
    assert "> [!comment] Jillian Kozyra" in text and "id:" in text
    assert s.push(note).status == "unchanged"
