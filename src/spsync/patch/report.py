"""The result of applying a note: change counts, warnings, and the errors that stop a patch."""

from __future__ import annotations

from dataclasses import dataclass, field


class ConflictError(Exception):
    pass


class BaseMismatchError(Exception):
    pass


@dataclass
class Report:
    modified: int = 0
    inserted: int = 0
    deleted: int = 0
    comments: int = 0
    replies: int = 0
    resolved: int = 0
    private_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any((self.modified, self.inserted, self.deleted, self.comments, self.replies, self.resolved))

    def summary(self) -> str:
        parts = [
            f"{self.modified} edited",
            f"{self.inserted} added",
            f"{self.deleted} removed",
            f"{self.comments} comments",
            f"{self.replies} replies",
        ]
        if self.resolved:
            parts.append(f"{self.resolved} resolution changes")
        return ", ".join(parts)
