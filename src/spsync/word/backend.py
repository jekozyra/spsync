"""The Word backend: reads documents through Word and applies note edits as a Word script."""

from __future__ import annotations

import hashlib
import time
from typing import Never
from urllib.parse import unquote

from ..local import WORD
from ..mdparse import PItem
from ..patch import Report
from ..reader import Item, join_items, read_items
from .app import close_doc, inspect, open_docs, open_url, recent_files, same_url, save_copy
from .planner import Planner
from .script import WordError, build_script, osa

# A pull downloads the document right after resolving it; reuse that copy instead of opening Word again.
COPY_REUSE_SECONDS = 120
# Word saves to the cloud in the background after the script finishes.
SAVE_SETTLE_SECONDS = 4


def md_tag(data: bytes) -> str:
    """An eTag for a Word document: the hash of its note Markdown, so metadata-only saves do not count."""
    return hashlib.sha1(join_items(read_items(data)).encode()).hexdigest()


class WordBackend:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, bytes]] = {}

    def _info(self, url: str, data: bytes) -> dict:
        return {
            "id": url,
            "name": unquote(url.split("?")[0].rsplit("/", 1)[-1]),
            "eTag": md_tag(data),
            "webUrl": url,
            "parentReference": {"driveId": WORD},
            "file": {},
        }

    def _guard_not_editing(self, url: str) -> None:
        """Refuse when the user has the document open for editing. Close a read-only copy."""
        for n, ro in open_docs():
            if same_url(n, url):
                if not ro:
                    raise WordError(
                        "The document is open for editing in Word. Close it there first.", 423, "resourceLocked"
                    )
                close_doc(n)

    def fetch(self, url: str) -> tuple[str, bytes]:
        self._guard_not_editing(url)
        name, _ = open_url(url, edit=False)
        data = save_copy(name)
        self._cache[name] = (time.time(), data)
        return name, data

    def resolve(self, ref: str) -> dict:
        name, data = self.fetch(ref)
        return self._info(name, data)

    def download(self, drive_id: str, item_id: str) -> bytes:
        hit = self._cache.get(item_id)
        if hit and time.time() - hit[0] < COPY_REUSE_SECONDS:
            return hit[1]
        return self.fetch(item_id)[1]

    def item(self, drive_id: str, item_id: str) -> dict:
        return self._info(item_id, self.download(drive_id, item_id))

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> Never:
        raise WordError("Word documents are updated through Word; use push.", 400, "unsupported")

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> Never:
        raise WordError("Create new documents in a OneDrive-synced folder instead.", 400, "unsupported")

    def me(self) -> Never:
        raise WordError("Word cannot report the signed-in account.", 400, "unsupported")

    def my_drive_id(self) -> str:
        return WORD

    def recent(self) -> list[dict]:
        out = []
        for url, name in recent_files():
            out.append(
                {
                    "id": url,
                    "name": name,
                    "webUrl": url,
                    "parentReference": {"driveId": WORD},
                    "lastModifiedBy": {"user": {"displayName": "recent in Word"}},
                }
            )
        return out

    def search(self, query: str, size: int = 25) -> list[dict]:
        terms = [t.lower() for t in query.split()]
        return [h for h in self.recent() if all(t in h["name"].lower() for t in terms)][:size]

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
        """Replay the note's edits in Word. Returns the report and the saved document, or None when nothing changed."""
        self._guard_not_editing(url)
        name, ro = open_url(url, edit=True)
        try:
            if ro:
                raise WordError("You only have view access to this document.", 403, "accessDenied")
            paras, comments = inspect(name)
            planner = Planner(base_docx, base_items, paras, comments)
            planner.check_fresh()
            plan = planner.plan(new_items)
            if dry_run or not plan.script:
                close_doc(name)
                return plan.report, None
            errs = osa(build_script(name, plan.script, suggest=suggest))
            for line in errs.splitlines():
                if line.strip():
                    plan.report.warnings.append("Word: " + line.strip())
            time.sleep(SAVE_SETTLE_SECONDS)
            data = save_copy(name)
        except Exception:
            # Close the document on any failure, then let the failure through.
            try:
                close_doc(name)
            except WordError:
                pass
            raise
        self._cache[name] = (time.time(), data)
        return plan.report, data
