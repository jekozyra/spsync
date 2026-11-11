"""Read a .docx into a block model and render it as Obsidian Markdown.

```text
.docx --parts--> styles, numbering, comments part
  w:body children --paragraphs--> Block (kind, level, md, locks, comment ids)
  Blocks + comments --items--> Item list --join_items--> note body
```

The package exports the interface that the patcher, the Word backend, and the sync core use.
"""

from __future__ import annotations

from .comments import CommentInfo, comment_callout, read_comments
from .items import Item, items_from_doc, join_items, read_items, read_items_and_media
from .paragraphs import Block, Reader, block_line
from .parts import Numbering, Styles, load_document, part_by_reltype, part_xml

__all__ = [
    "Block",
    "CommentInfo",
    "Item",
    "Numbering",
    "Reader",
    "Styles",
    "block_line",
    "comment_callout",
    "items_from_doc",
    "join_items",
    "load_document",
    "part_by_reltype",
    "part_xml",
    "read_comments",
    "read_items",
    "read_items_and_media",
]
