import io

import pytest
from docx import Document

from spsync.core import Session, SyncError
from spsync.graph import GraphError
from spsync.reader import load_document


def docx_bytes(paras):
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class FakeGraph:
    def __init__(self, data):
        self.data = data
        self.version = 1
        self.uploads = 0
        self.locked = False

    def _item(self):
        return {
            "id": "ITEM",
            "name": "Plan.docx",
            "eTag": f'"v{self.version}"',
            "webUrl": "https://contoso.sharepoint.com/sites/x/Plan.docx",
            "parentReference": {"driveId": "DRIVE"},
            "file": {},
        }

    def resolve(self, ref):
        return self._item()

    def item(self, d, i):
        return self._item()

    def download(self, d, i):
        return self.data

    def upload(self, d, i, data, etag):
        if self.locked:
            raise GraphError(423, "resourceLocked", "locked")
        if etag != self._item()["eTag"]:
            raise GraphError(412, "preconditionFailed", "etag")
        self.data = data
        self.version += 1
        self.uploads += 1
        return self._item()

    def me(self):
        return {"displayName": "Jillian Kozyra"}

    def remote_edit(self, fn):
        doc = load_document(self.data)
        fn(doc)
        buf = io.BytesIO()
        doc.save(buf)
        self.data = buf.getvalue()
        self.version += 1


@pytest.fixture
def env(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    g = FakeGraph(docx_bytes(["Alpha paragraph.", "Beta paragraph.", "Gamma paragraph."]))
    s = Session(tmp_path, graph=g)
    note = s.pull("https://x")
    return s, g, note


def texts(g):
    return [p.text for p in load_document(g.data).paragraphs if p.text]


def test_pull_writes_note(env):
    _s, _g, note = env
    text = note.read_text()
    assert note.name == "Plan.md"
    assert "spsync: DRIVE:ITEM" in text and "Alpha paragraph." in text


def test_push_roundtrip(env):
    s, g, note = env
    note.write_text(note.read_text().replace("Beta paragraph.", "Beta paragraph, edited."))
    res = s.push(note)
    assert res.status == "pushed"
    assert texts(g) == ["Alpha paragraph.", "Beta paragraph, edited.", "Gamma paragraph."]
    assert s.push(note).status == "unchanged"


def test_push_refuses_stale_base(env):
    s, g, note = env
    g.remote_edit(lambda d: d.add_paragraph("Remote addition."))
    note.write_text(note.read_text().replace("Alpha", "Alpha!"))
    with pytest.raises(SyncError, match="changed in SharePoint"):
        s.push(note)


def test_locked_document(env):
    s, g, note = env
    g.locked = True
    note.write_text(note.read_text().replace("Alpha", "Alpha!"))
    with pytest.raises(SyncError, match="locked"):
        s.push(note)


def test_sync_pulls_remote_only(env):
    s, g, note = env
    g.remote_edit(lambda d: d.add_paragraph("Remote addition."))
    assert s.sync(note).status == "pulled"
    assert "Remote addition." in note.read_text()


def test_sync_merges_disjoint_edits(env):
    s, g, note = env

    def edit(d):
        d.paragraphs[2].runs[0].text = "Gamma paragraph, remote."

    g.remote_edit(edit)
    note.write_text(note.read_text().replace("Alpha paragraph.", "Alpha paragraph, local."))
    res = s.sync(note)
    assert res.status == "merged", res.message
    assert texts(g) == ["Alpha paragraph, local.", "Beta paragraph.", "Gamma paragraph, remote."]
    assert "Gamma paragraph, remote." in note.read_text()


def test_adjacent_edits_merge_without_conflict():
    from spsync.core import merge_items

    md, n = merge_items(["## H", "Para.", "Tail."], ["## Renamed", "Para.", "Tail."], ["## H", "Para, remote.", "Tail."])
    assert n == 0 and "## Renamed" in md and "Para, remote." in md


def test_sync_conflict_then_resolve(env):
    s, g, note = env

    def edit(d):
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
    note.write_text(text[:start] + text[end:].replace("Beta local.", "") .replace("Gamma", "Gamma"))
    note.write_text(note.read_text().replace("Beta local.", "Beta merged."))
    res = s.sync(note)
    assert res.status == "pushed", res.message
    assert texts(g) == ["Alpha paragraph.", "Beta merged.", "Gamma paragraph."]


def test_new_comment_gets_id_after_push(env):
    s, _g, note = env
    note.write_text(note.read_text().replace("Beta paragraph.", "Beta paragraph.\n\n> [!comment] Can we cut this?"))
    s.push(note)
    text = note.read_text()
    assert "> [!comment] Jillian Kozyra" in text and "id:" in text
    assert s.push(note).status == "unchanged"
