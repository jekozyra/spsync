"""Local backend: work on .docx files synced by the OneDrive app, no Graph consent needed.

The OneDrive client uploads whatever spsync writes. Item ids are absolute file paths, the drive id
is `local`, and the eTag is the file's modification time and size.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

from .auth import load_config
from .graph import Graph, GraphError

LOCAL = "local"


class Backend(Protocol):
    def resolve(self, ref: str) -> dict: ...
    def item(self, drive_id: str, item_id: str) -> dict: ...
    def download(self, drive_id: str, item_id: str) -> bytes: ...
    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> dict: ...
    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> dict: ...
    def search(self, query: str, size: int = 25) -> list[dict]: ...
    def recent(self) -> list[dict]: ...
    def me(self) -> dict: ...
    def my_drive_id(self) -> str: ...


def default_roots() -> list[Path]:
    cfg = load_config()
    if cfg.get("roots"):
        return [Path(r).expanduser() for r in cfg["roots"]]
    env = os.environ.get("SPSYNC_ROOTS")
    if env:
        return [Path(r).expanduser() for r in env.split(os.pathsep) if r]
    cloud = Path.home() / "Library" / "CloudStorage"
    return sorted(p for p in cloud.glob("OneDrive*") if p.is_dir()) if cloud.exists() else []


def link_file_name(url: str) -> str | None:
    """File name from a SharePoint/OneDrive link: the Doc.aspx ?file= parameter or the last path part."""
    from urllib.parse import parse_qs, unquote, urlparse

    u = urlparse(url)
    name = (parse_qs(u.query).get("file") or [None])[0]
    if not name:
        last = unquote(u.path.rsplit("/", 1)[-1])
        name = last if last.lower().endswith(".docx") else None
    return name


def lock_files(path: Path) -> list[Path]:
    """Word's owner files: ~$ plus the name, or ~$ replacing the first two characters."""
    names = {"~$" + path.name, "~$" + path.name[2:]}
    return [path.with_name(n) for n in names if path.with_name(n).exists()]


def _full_name() -> str:
    try:
        out = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or os.environ.get("USER", "spsync")


class LocalBackend:
    def __init__(self, roots: list[Path] | None = None, author: str | None = None):
        self.roots = roots if roots is not None else default_roots()
        self.author = author or load_config().get("author") or _full_name()

    # ---- items ----
    @staticmethod
    def _info(path: Path) -> dict:
        path = path.resolve()
        if not path.exists():
            raise GraphError(404, "itemNotFound", f"{path} does not exist")
        st = path.stat()
        d = {
            "id": str(path),
            "name": path.name,
            "eTag": f"{st.st_mtime_ns}-{st.st_size}",
            "webUrl": path.as_uri(),
            "lastModifiedDateTime": __import__("datetime").datetime.fromtimestamp(st.st_mtime).isoformat(),
            "parentReference": {"driveId": LOCAL},
        }
        d["folder" if path.is_dir() else "file"] = {}
        return d

    def resolve(self, ref: str) -> dict:
        if ref.startswith(LOCAL + ":"):
            ref = ref[len(LOCAL) + 1:]
        if ref.startswith("file://"):
            from urllib.parse import unquote

            ref = unquote(ref[7:])
        if ref == "me" and self.roots:
            return self._info(self.roots[0])
        path = Path(ref).expanduser()
        if not path.exists():
            raise GraphError(404, "itemNotFound", f"No such file: {ref}. In local mode, pass a path or use `spsync search`.")
        return self._info(path)

    def item(self, drive_id: str, item_id: str) -> dict:
        return self._info(Path(item_id))

    def download(self, drive_id: str, item_id: str) -> bytes:
        return Path(item_id).read_bytes()  # reading also hydrates OneDrive online-only files

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> dict:
        path = Path(item_id)
        locks = lock_files(path)
        if locks:
            raise GraphError(423, "resourceLocked", f"open in Word on this Mac; close it first ({locks[0].name})")
        if etag and self._info(path)["eTag"] != etag:
            raise GraphError(412, "preconditionFailed", "file changed since last pull")
        # Rewrite in place so OneDrive keeps the same item and its version history.
        with open(path, "r+b") as f:
            f.write(data)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
        return self._info(path)

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> dict:
        path = Path(parent_id) / name
        if path.exists():
            raise GraphError(409, "nameAlreadyExists", f"{path} already exists")
        path.write_bytes(data)
        return self._info(path)

    def my_drive_id(self) -> str:
        return LOCAL

    def me(self) -> dict:
        return {"displayName": self.author}

    # ---- discovery ----
    def _docs(self):
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    if fn.lower().endswith(".docx") and not fn.startswith(("~$", ".")):
                        yield Path(dirpath) / fn

    def _hit(self, path: Path, root_rel: bool = True) -> dict:
        d = self._info(path)
        d["lastModifiedBy"] = {"user": {"displayName": self._where(path)}}
        return d

    def _where(self, path: Path) -> str:
        for root in self.roots:
            try:
                rel = path.parent.relative_to(root)
            except ValueError:
                continue
            return f"{root.name}/{rel}" if str(rel) != "." else root.name
        return str(path.parent)

    def search(self, query: str, size: int = 25, docx_only: bool = True) -> list[dict]:
        terms = [t.lower() for t in query.split()]
        found = [p for p in self._docs() if all(t in str(p.relative_to(self._root_of(p))).lower() for t in terms)]
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [self._hit(p) for p in found[:size]]

    def _root_of(self, path: Path) -> Path:
        for root in self.roots:
            if path.is_relative_to(root):
                return root
        return path.parent

    def recent(self) -> list[dict]:
        found = sorted(self._docs(), key=lambda p: p.stat().st_mtime, reverse=True)
        return [self._hit(p) for p in found[:50]]


class Router:
    """Send each operation to the local backend or Graph, based on the item."""

    def __init__(self, mode: str):
        self.mode = mode
        self.local = LocalBackend()
        self._graph: Graph | None = None
        self._word = None

    @property
    def word(self):
        if self._word is None:
            from .word import WordBackend

            self._word = WordBackend()
        return self._word

    @property
    def graph(self) -> Graph:
        if self._graph is None:
            self._graph = Graph()
        return self._graph

    def _pick(self, drive_id: str):
        if drive_id == "word":
            return self.word
        return self.local if drive_id == LOCAL else self.graph

    def resolve(self, ref):
        if ref.startswith("word:"):
            return self.word.resolve(ref[5:])
        if ref.endswith(".url") and Path(ref).expanduser().exists():
            for line in Path(ref).expanduser().read_text(errors="replace").splitlines():
                if line.startswith("URL="):
                    return self.word.resolve(line[4:].strip())
        is_url = ref.startswith("http")
        if not is_url and (ref.startswith((LOCAL + ":", "file://", "/", "~", ".")) or Path(ref).expanduser().exists() or self.mode == LOCAL):
            return self.local.resolve(ref)
        if is_url and self.mode == LOCAL:
            name = link_file_name(ref)
            if name:
                matches = [h for h in self.local.search(name, size=50) if h["name"].lower() == name.lower()]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    where = "; ".join(self.local._where(Path(m["id"])) for m in matches)
                    raise GraphError(409, "ambiguous", f"Several synced copies of {name} ({where}). Pull one by path.")
            # Not synced locally: let Word open it.
            return self.word.resolve(ref)
            raise GraphError(
                400,
                "localMode",
                "SharePoint links need Graph sign-in, which isn't approved yet. Sync the library with OneDrive "
                "(SharePoint > Sync or Add shortcut to My files), then use `spsync search` or a file path.",
            )
        return self.graph.resolve(ref)

    def item(self, d, i):
        return self._pick(d).item(d, i)

    def download(self, d, i):
        return self._pick(d).download(d, i)

    def upload(self, d, i, data, etag):
        return self._pick(d).upload(d, i, data, etag)

    def create(self, d, p, name, data):
        return self._pick(d).create(d, p, name, data)

    def my_drive_id(self):
        return LOCAL if self.mode == LOCAL else self.graph.my_drive_id()

    def me(self):
        return self.local.me() if self.mode == LOCAL else self.graph.me()

    def _with_word(self, hits, word_hits):
        names = {h["name"].lower() for h in hits}
        return hits + [h for h in word_hits if h["name"].lower() not in names]

    def _word_hits(self, fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001 - Word missing or not scriptable
            return []

    def search(self, query, size=25):
        if self.mode != LOCAL:
            return self.graph.search(query, size)
        return self._with_word(self.local.search(query, size), self._word_hits(lambda: self.word.search(query, size)))[:size]

    def recent(self):
        if self.mode != LOCAL:
            return self.graph.recent()
        return self._with_word(self._word_hits(self.word.recent), self.local.recent())


def backend() -> Router:
    mode = os.environ.get("SPSYNC_BACKEND") or load_config().get("backend") or LOCAL
    return Router(mode)
