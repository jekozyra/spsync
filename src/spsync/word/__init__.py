"""Word backend: use the signed-in Word app to read and edit cloud documents.

Word is already trusted by the tenant, so this needs no Graph consent. Pulls open the document
read-only and save a local copy. Pushes open it for editing and replay each change through Word's
scripting interface, so co-authoring, version history, and tracked changes work as in Word.

```text
script.py   AppleScript literals, osascript, and the script wrapper
app.py      Word app operations: open, inspect, save a copy, close, Automation access
text.py     Text matching between the base document and Word's paragraphs
ops.py      AppleScript for one change: edit, insert, delete, restyle, comment
planner.py  The plan: which ops to run, in which order
backend.py  WordBackend, the Backend implementation
```
"""

from __future__ import annotations

from ..local import WORD
from .app import automation_allowed
from .backend import WordBackend, md_tag
from .planner import Plan, Planner
from .script import WordError, build_script, lit
from .text import align, offset_map, unique_context

__all__ = [
    "WORD",
    "Plan",
    "Planner",
    "WordBackend",
    "WordError",
    "align",
    "automation_allowed",
    "build_script",
    "lit",
    "md_tag",
    "offset_map",
    "unique_context",
]
