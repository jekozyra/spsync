"""Word app operations: open, inspect, save a copy, and close cloud documents, and check Automation access."""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .script import FS, GS, RS, WordError, find_doc, lit, osa

TMP = Path.home() / "Documents" / ".spsync-word"
OPEN_TIMEOUT_SECONDS = 120
OPEN_POLL_SECONDS = 1.5
# Word reports a document as open before it finishes loading its content.
LOAD_SETTLE_SECONDS = 2
COPY_HASH_CHARS = 10
# Characters that `ms-word:` links keep unescaped in a SharePoint URL.
URL_SAFE = ":/?&=%#~+,;@!$'()*"
WORD_BUNDLE_ID = "com.microsoft.Word"
WORD_LAUNCH_TIMEOUT_SECONDS = 60
WORD_LAUNCH_POLL_SECONDS = 0.5
# The first Apple event can wait on the macOS permission prompt until the user answers. The launch wait and
# this wait together stay under the plugin's five-minute limit for one CLI run.
PERMISSION_TIMEOUT_SECONDS = 180
# osascript ends its message with this code when macOS denies Automation access to Word.
NOT_AUTHORIZED_CODE = "(-1743)"


def open_docs() -> list[tuple[str, bool]]:
    """(full name, read only) for every document open in Word."""
    out = osa(
        """tell application "Microsoft Word"
  set out to ""
  repeat with i from 1 to (count of documents)
    set out to out & (full name of document i) & (character id 31) & (read only of document i) & (character id 30)
  end repeat
  return out
end tell"""
    )
    docs = []
    for rec in out.split(RS):
        if FS in rec:
            name, ro = rec.split(FS, 1)
            docs.append((name, ro.strip() == "true"))
    return docs


def same_url(a: str, b: str) -> bool:
    return unquote(a).rstrip("/").lower() == unquote(b).rstrip("/").lower()


def link_name(url: str) -> str | None:
    u = urlparse(url)
    name = (parse_qs(u.query).get("file") or [None])[0]
    if not name:
        last = unquote(u.path.rsplit("/", 1)[-1])
        name = last or None
    return name


def _opened(url: str, before: set[str], docs: list[tuple[str, bool]]) -> tuple[str, bool] | None:
    """The open document that matches `url`: the same URL, a newly opened cloud document, or the same file name."""
    for n, ro in docs:
        if same_url(n, url.split("?")[0]) or (n not in before and n.startswith("http")):
            return n, ro
    name = link_name(url)
    if name:
        for n, ro in docs:
            if n.startswith("http") and unquote(n).rsplit("/", 1)[-1].lower() == name.lower():
                return n, ro
    return None


def open_url(url: str, *, edit: bool, timeout: int = OPEN_TIMEOUT_SECONDS) -> tuple[str, bool]:
    """Open `url` in Word without bringing Word to the front. Returns (Word's canonical URL, read_only).

    The `-g` flag keeps the foreground app in front when Word is closed, in front, or in the background.
    """
    before = {n for n, _ in open_docs()}
    mode = "ofe" if edit else "ofv"
    target = quote(url, safe=URL_SAFE)
    subprocess.run(["open", "-g", f"ms-word:{mode}|u|{target}"], check=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(OPEN_POLL_SECONDS)
        try:
            docs = open_docs()
        except WordError:
            continue
        found = _opened(url, before, docs)
        if found is not None:
            time.sleep(LOAD_SETTLE_SECONDS)
            return found
    raise WordError(
        "Word didn't open the document. Check the link opens in Word, and that Word is signed in.", 404, "notFound"
    )


def close_doc(url: str, *, save: bool = False) -> None:
    osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  close d saving {"yes" if save else "no"}
end tell"""
    )


def save_copy(url: str) -> bytes:
    """Save the open document as a local copy (which closes it in Word) and return the bytes."""
    TMP.mkdir(parents=True, exist_ok=True)
    dest = TMP / f"copy-{hashlib.sha1((url + str(time.time())).encode()).hexdigest()[:COPY_HASH_CHARS]}.docx"
    osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  save as d file name {lit(str(dest))} file format format document
  repeat with i from 1 to (count of documents)
    if (name of document i) is {lit(dest.name)} then
      close document i saving no
      exit repeat
    end if
  end repeat
end tell"""
    )
    data = dest.read_bytes()
    dest.unlink(missing_ok=True)
    return data


def _word_running() -> bool:
    return osa(f'application id "{WORD_BUNDLE_ID}" is running') == "true"


def _start_hidden() -> None:
    subprocess.run(["open", "-g", "-j", "-b", WORD_BUNDLE_ID], check=False)
    deadline = time.time() + WORD_LAUNCH_TIMEOUT_SECONDS
    while not _word_running():
        if time.time() > deadline:
            raise WordError("Word did not start.", 504, "timeout")
        time.sleep(WORD_LAUNCH_POLL_SECONDS)


def automation_allowed() -> bool:
    """Whether macOS lets this process control Word through Apple events.

    When Word is closed, this starts Word hidden and in the background, and quits Word afterward.
    The first call can show the macOS permission prompt, and waits for the answer.
    Raises WordError when Word does not start or does not answer.
    """
    started = not _word_running()
    if started:
        _start_hidden()
    try:
        osa(f'tell application id "{WORD_BUNDLE_ID}" to get name', timeout=PERMISSION_TIMEOUT_SECONDS)
    except WordError as exc:
        if exc.message.endswith(NOT_AUTHORIZED_CODE):
            return False
        raise
    finally:
        if started:
            try:
                osa(f'tell application id "{WORD_BUNDLE_ID}" to quit saving no')
            except WordError:
                pass  # Word without permission ignores quit; it stays hidden until the user quits it.
    return True


def recent_files() -> list[tuple[str, str]]:
    """(URL, name) for each cloud .docx in Word's recent files."""
    out = osa(
        """tell application "Microsoft Word"
  set out to ""
  repeat with i from 1 to (count of recent files)
    set out to out & (path of recent file i) & (character id 31) & (name of recent file i) & (character id 30)
  end repeat
  return out
end tell"""
    )
    files = []
    for rec in out.split(RS):
        if FS in rec:
            folder, name = rec.split(FS, 1)
            if folder.startswith("http") and name.lower().endswith(".docx"):
                files.append((folder.rstrip("/") + "/" + name, name))
    return files


def inspect(url: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Paragraph texts and (author, text) for every comment, in document order."""
    out = osa(
        f"""tell application "Microsoft Word"
{find_doc(url)}
  set out to ""
  repeat with i from 1 to (count of paragraphs of d)
    set out to out & (content of text object of paragraph i of d) & (character id 30)
  end repeat
  set out to out & (character id 29)
  repeat with i from 1 to (count of Word comments of d)
    set c to Word comment i of d
    set out to out & (author of c) & (character id 31) & (content of comment text of c) & (character id 30)
  end repeat
  return out
end tell"""
    )
    paras_s, _, comments_s = out.partition(GS)
    paras = paras_s.split(RS)[:-1]
    comments = []
    for rec in comments_s.split(RS):
        if FS in rec:
            a, t = rec.split(FS, 1)
            comments.append((a, t))
    return paras, comments
