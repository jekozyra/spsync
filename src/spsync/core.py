"""Pull, push, sync, and create operations shared by the CLI and the watcher."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from merge3 import Merge3

from .graph import GraphError
from .local import Backend, backend
from .mdparse import LIST, parse_note, split_frontmatter, with_frontmatter
from .patch import BaseMismatchError, ConflictError, apply_note
from .reader import join_items, read_items, read_items_and_media
from .store import Binding, Store, find_vault

FM_URL = "sharepoint"
FM_REF = "spsync"
FM_SYNCED = "spsync_synced"


class SyncError(Exception):
    pass


class RemoteChangedError(SyncError):
    pass


@dataclass
class Result:
    status: str  # unchanged | pulled | pushed | merged | conflict | dry-run
    message: str = ""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_name(name: str) -> str:
    stem = re.sub(r"\.docx$", "", name, flags=re.IGNORECASE)
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "-", stem).strip() or "Untitled"


def _initials(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name)[:3]).upper()


class Session:
    """Binds a Graph client to a vault."""

    def __init__(self, vault: Path, graph: Backend | None = None):
        self.vault = vault
        self.store = Store(vault)
        self._graph = graph
        self._me = None

    @classmethod
    def for_path(cls, path: Path, graph: Backend | None = None) -> Session:
        return cls(find_vault(path), graph)

    @property
    def graph(self) -> Backend:
        if self._graph is None:
            self._graph = backend()
        return self._graph

    def me(self) -> tuple[str, str]:
        if self._me is None:
            info = self.graph.me()
            name = info.get("displayName") or info.get("userPrincipalName") or "spsync"
            self._me = (name, _initials(name))
        return self._me

    # ---- note helpers ----
    def binding_for(self, note: Path) -> tuple[Binding, bytes]:
        fm, _ = split_frontmatter(note.read_text())
        ref = fm.get(FM_REF)
        if not ref:
            raise SyncError(f"{note} is not linked to SharePoint (no `{FM_REF}` property). Use `spsync pull` or `spsync new`.")
        loaded = self.store.load(str(ref))
        if loaded is None:
            raise SyncError(f"No sync state for {note}. Run `spsync pull {fm.get(FM_URL) or ref} --force`.")
        return loaded

    def write_note(self, note: Path, b: Binding, body: str):
        fm = {}
        if note.exists():
            fm, _ = split_frontmatter(note.read_text())
        fm[FM_URL] = b.web_url
        fm[FM_REF] = b.ref
        fm[FM_SYNCED] = b.pulled_at
        text = with_frontmatter(fm, body)
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists() or note.read_text() != text:
            note.write_text(text)

    def _bind(self, item: dict, data: bytes, note: Path) -> Binding:
        items, media = read_items_and_media(data)
        if media:
            folder = self.vault / "SharePoint" / "_media"
            folder.mkdir(parents=True, exist_ok=True)
            for name, blob in media.items():
                path = folder / name
                if not path.exists():
                    path.write_bytes(blob)
        b = Binding(
            drive_id=item["parentReference"]["driveId"],
            item_id=item["id"],
            etag=item.get("eTag", ""),
            name=item.get("name", ""),
            web_url=item.get("webUrl", ""),
            note=str(note.resolve().relative_to(self.vault.resolve())),
            pulled_at=_now(),
            items=items,
        )
        self.store.save(b, data)
        self.write_note(note, b, join_items(items))
        return b

    @staticmethod
    def local_changed(b: Binding, note: Path):
        _, pitems = parse_note(note.read_text())
        return [p.md for p in pitems] != [i.md for i in b.items], pitems

    def _fetch(self, b: Binding) -> tuple[dict, bytes]:
        data = self.graph.download(b.drive_id, b.item_id)
        item = self.graph.item(b.drive_id, b.item_id)
        return item, data

    # ---- operations ----
    def pull(self, ref: str, out: Path | None = None, force: bool = False) -> Path:
        item = self.graph.resolve(ref)
        if "folder" in item:
            raise SyncError("That link is a folder. Pull a single Word document.")
        if not item.get("name", "").lower().endswith(".docx"):
            raise SyncError(f"{item.get('name')} is not a .docx Word document. Only Word documents are supported.")
        drive_id = item["parentReference"]["driveId"]
        existing = self.store.load(f"{drive_id}:{item['id']}")
        if out is None:
            out = self.vault / existing[0].note if existing else self.vault / "SharePoint" / f"{_safe_name(item['name'])}.md"
        if existing and out.exists() and not force:
            changed, _ = self.local_changed(existing[0], out)
            if changed:
                raise SyncError(f"{out} has local edits. Use `spsync sync` to merge, or `--force` to discard them.")
        if not existing and out.exists() and not force:
            fm, _ = split_frontmatter(out.read_text())
            if fm.get(FM_REF) != f"{drive_id}:{item['id']}":
                raise SyncError(f"{out} already exists. Pass --out to choose another path, or --force to overwrite.")
        data = self.graph.download(drive_id, item["id"])
        self._bind(item, data, out)
        return out

    def push(self, note: Path, *, suggest: bool = False, dry_run: bool = False) -> Result:
        b, base = self.binding_for(note)
        changed, pitems = self.local_changed(b, note)
        if not changed:
            return Result("unchanged", "No local edits.")
        if b.drive_id == "word":
            return self._push_word(note, b, base, pitems, suggest=suggest, dry_run=dry_run)
        author, initials = self.me() if not dry_run else ("spsync", "")
        try:
            out, report = apply_note(base, b.items, pitems, author=author, initials=initials, suggest=suggest)
        except (ConflictError, BaseMismatchError) as exc:
            raise SyncError(str(exc)) from exc
        msg = report.summary() + "".join(f"\n  warning: {w}" for w in report.warnings)
        if dry_run:
            return Result("dry-run", msg)
        if not report.changed:
            return Result("unchanged", "Nothing to send." + "".join(f"\n  warning: {w}" for w in report.warnings))
        try:
            self.graph.upload(b.drive_id, b.item_id, out, b.etag)
        except GraphError as exc:
            if exc.status == 412:
                raise RemoteChangedError("The document changed in SharePoint since your last pull. Run `spsync sync` to merge.") from exc
            if exc.status == 423:
                raise SyncError(f"The document is locked ({exc.message}). Try again shortly.") from exc
            raise
        item, data = self._fetch(b)
        self._bind(item, data, note)
        return Result("pushed", msg)

    def _push_word(self, note, b, base, pitems, *, suggest, dry_run) -> Result:
        if any(p.t == "conflict" for p in pitems):
            raise SyncError("The note still has [!conflict] callouts. Resolve them and delete the callouts first.")
        try:
            report, data = self.graph.word.apply(b.item_id, base, b.items, pitems, suggest=suggest, dry_run=dry_run)
        except GraphError as exc:
            if exc.status == 412:
                raise RemoteChangedError("The document changed since your last pull. Run `spsync sync` to merge.") from exc
            raise
        msg = report.summary() + "".join(f"\n  warning: {w}" for w in report.warnings)
        if dry_run:
            return Result("dry-run", msg)
        if data is None:
            return Result("unchanged", "Nothing to send." + "".join(f"\n  warning: {w}" for w in report.warnings))
        item = self.graph.item(b.drive_id, b.item_id)
        self._bind(item, data, note)
        return Result("pushed", msg)

    def sync(self, note: Path, *, suggest: bool = False) -> Result:
        b, _ = self.binding_for(note)
        local, pitems = self.local_changed(b, note)
        if b.drive_id == "word" and local:
            # Word mode checks freshness while applying, which saves opening the document twice.
            try:
                return self.push(note, suggest=suggest)
            except RemoteChangedError:
                pass
        item = self.graph.item(b.drive_id, b.item_id)
        remote_items = None
        data = None
        if item.get("eTag") != b.etag:
            data = self.graph.download(b.drive_id, b.item_id)
            remote_items = read_items(data)
            if [i.md for i in remote_items] == [i.md for i in b.items]:
                # Metadata-only change. Adopt the new version as the base.
                b2 = Binding(**{**b.__dict__, "etag": item["eTag"], "items": remote_items, "pulled_at": _now()})
                self.store.save(b2, data)
                remote_items = None
        if remote_items is None:
            if not local:
                return Result("unchanged", "Up to date.")
            return self.push(note, suggest=suggest)
        if not local:
            self._bind(item, data, note)
            return Result("pulled", "Pulled changes from SharePoint.")
        # Both sides changed: three-way merge at block level, then push the result.
        merged, conflicts = merge_items([i.md for i in b.items], [p.md for p in pitems], [i.md for i in remote_items])
        self._bind(item, data, note)
        _fm, _ = split_frontmatter(note.read_text())
        self.write_note(note, self.store.load(f"{b.drive_id}:{b.item_id}")[0], merged)
        if conflicts:
            return Result("conflict", f"{conflicts} conflicting section(s). Look for [!conflict] callouts in the note, fix them, delete the callouts, then sync again.")
        res = self.push(note, suggest=suggest)
        return Result("merged", "Merged SharePoint changes with your edits. " + res.message)

    def new(self, note: Path, folder_ref: str, name: str | None = None, *, suggest: bool = False) -> Result:
        fm, _body = split_frontmatter(note.read_text())
        if fm.get(FM_REF):
            raise SyncError(f"{note} is already linked to SharePoint.")
        folder = self.graph.resolve(folder_ref)
        if "folder" not in folder and "root" not in folder:
            raise SyncError("The --folder link must point to a SharePoint or OneDrive folder.")
        drive_id = (folder.get("parentReference") or {}).get("driveId") or self.graph.my_drive_id()
        buf = io.BytesIO()
        Document().save(buf)
        blank = buf.getvalue()
        _, pitems = parse_note(note.read_text())
        author, initials = self.me()
        out, report = apply_note(blank, read_items(blank), pitems, author=author, initials=initials, suggest=suggest)
        filename = (name or note.stem)
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        item = self.graph.create(drive_id, folder["id"], filename, out)
        item = self.graph.item(item["parentReference"]["driveId"], item["id"])
        data = self.graph.download(item["parentReference"]["driveId"], item["id"])
        self._bind(item, data, note)
        return Result("pushed", f"Created {item.get('webUrl')}\n{report.summary()}")


def _is_list(md: str) -> bool:
    return bool(LIST.match(md.split("\n", 1)[0])) and not md.startswith(">")


def join_md(mds: list[str]) -> str:
    out = []
    for k, md in enumerate(mds):
        if k:
            out.append("\n" if _is_list(mds[k - 1]) and _is_list(md) else "\n\n")
        out.append(md)
    return "".join(out) + "\n"


def conflict_callout(remote: list[str]) -> str:
    lines = ["> [!conflict] SharePoint version of this section (changed while you were editing). Keep what you want, then delete this callout."]
    for md in remote or ["(deleted in SharePoint)"]:
        for line in md.split("\n"):
            lines.append("> " + line)
        lines.append(">")
    return "\n".join(lines).rstrip(">\n")


def merge_items(base: list[str], local: list[str], remote: list[str]) -> tuple[str, int]:
    merged: list[str] = []
    conflicts = 0
    for group in Merge3(base, local, remote).merge_groups():
        kind = group[0]
        if kind == "conflict":
            _, b, a, r = group
            if len(b) == len(a) == len(r):
                # Same shape on all sides: settle it paragraph by paragraph.
                for bx, ax, rx in zip(b, a, r, strict=True):
                    if ax == rx or rx == bx:
                        merged.append(ax)
                    elif ax == bx:
                        merged.append(rx)
                    else:
                        merged.extend([ax, conflict_callout([rx])])
                        conflicts += 1
                continue
            merged.extend(a)
            merged.append(conflict_callout(r))
            conflicts += 1
        else:
            merged.extend(group[1])
    return join_md(merged), conflicts
