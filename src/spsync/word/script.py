"""AppleScript plumbing: string literals, running a script, and the wrapper for a list of ops."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..graph import GraphError

# Record, field, and group separators in script output.
RS, FS, GS = "\x1e", "\x1f", "\x1d"
SCRIPT_TIMEOUT_SECONDS = 600
# Character id 11 is a manual line break in Word.
MANUAL_LINE_BREAK = 11
FIRST_PRINTABLE = 32


class WordError(GraphError):
    def __init__(self, message: str, status: int = 500, code: str = "word") -> None:
        super().__init__(status, code, message)


def lit(s: str, newline: int = MANUAL_LINE_BREAK) -> str:
    """An AppleScript expression for `s`. `\\n` becomes a manual line break by default."""
    parts: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            parts.append('"' + "".join(buf) + '"')
            buf.clear()

    for ch in s:
        o = ord(ch)
        if ch == '"':
            buf.append('\\"')
        elif ch == "\\":
            buf.append("\\\\")
        elif ch == "\n":
            flush()
            parts.append(f"(character id {newline})")
        elif o < FIRST_PRINTABLE:
            flush()
            parts.append(f"(character id {o})")
        else:
            buf.append(ch)
    flush()
    return " & ".join(parts) if parts else '""'


def osa(script: str, timeout: int = SCRIPT_TIMEOUT_SECONDS) -> str:
    """Run an AppleScript and return its output. A script error becomes a WordError."""
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False, encoding="utf-8") as f:
        f.write(script)
        path = f.name
    try:
        p = subprocess.run(["osascript", path], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise WordError("Word did not respond in time.") from exc
    finally:
        Path(path).unlink(missing_ok=True)
    if p.returncode != 0:
        raise WordError(p.stderr.strip() or "AppleScript failed")
    out = p.stdout
    return out.removesuffix("\n")


def find_doc(url: str) -> str:
    """AppleScript that sets `d` to the open document named `url`, or fails."""
    return f"""
  set d to missing value
  repeat with i from 1 to (count of documents)
    if (full name of document i) is {lit(url)} then
      set d to document i
      exit repeat
    end if
  end repeat
  if d is missing value then error "spsync: the document is not open in Word"
"""


SAME = """on same(a, b)
  considering case
    return a is b
  end considering
end same
"""


def build_script(url: str, ops: list[str], *, suggest: bool) -> str:
    """The full push script: run every op with tracked changes on or off, then save."""
    return (
        SAME
        + f"""tell application "Microsoft Word"
{find_doc(url)}
  set errs to ""
  set oldTrack to track revisions of d
  set track revisions of d to {"true" if suggest else "false"}
{"".join(ops)}
  set track revisions of d to oldTrack
  save d
  return errs
end tell"""
    )
