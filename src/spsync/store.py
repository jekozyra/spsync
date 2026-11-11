"""Per-vault sync state: the pulled .docx and its block map, kept under <vault>/.spsync."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .reader import Item

STATE = ".spsync"


def find_vault(start: Path) -> Path:
    start = start.resolve()
    here = start if start.is_dir() else start.parent
    for p in [here, *here.parents]:
        if (p / ".obsidian").is_dir():
            return p
    return here


@dataclass
class Binding:
    drive_id: str
    item_id: str
    etag: str
    name: str
    web_url: str
    note: str  # path relative to vault
    pulled_at: str
    items: list[Item] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.drive_id}:{self.item_id}"

    def to_json(self) -> dict:
        d = asdict(self)
        d["items"] = [i.to_json() for i in self.items]
        return d

    @classmethod
    def from_json(cls, d: dict) -> Binding:
        d = dict(d)
        d["items"] = [Item.from_json(i) for i in d.get("items", [])]
        return cls(**d)


class Store:
    def __init__(self, vault: Path):
        self.vault = vault
        self.root = vault / STATE

    def _dir(self, ref: str) -> Path:
        return self.root / hashlib.sha1(ref.encode()).hexdigest()[:16]

    def save(self, b: Binding, base_docx: bytes):
        d = self._dir(b.ref)
        d.mkdir(parents=True, exist_ok=True)
        (d / "base.docx").write_bytes(base_docx)
        (d / "meta.json").write_text(json.dumps(b.to_json(), indent=1))

    def load(self, ref: str) -> tuple[Binding, bytes] | None:
        d = self._dir(ref)
        if not (d / "meta.json").exists():
            return None
        b = Binding.from_json(json.loads((d / "meta.json").read_text()))
        return b, (d / "base.docx").read_bytes()

    def all(self) -> list[Binding]:
        if not self.root.exists():
            return []
        out = []
        for meta in sorted(self.root.glob("*/meta.json")):
            out.append(Binding.from_json(json.loads(meta.read_text())))
        return out

    def remove(self, ref: str):
        d = self._dir(ref)
        for f in d.glob("*"):
            f.unlink()
        if d.exists():
            d.rmdir()
