"""Word mode keeps the foreground app: a pull and a push through Word do not bring Word to the front.

These checks drive a real SharePoint document that OneDrive does not sync. Set SPSYNC_TEST_SHAREPOINT_URL
to the link of a test document. Each check adds one paragraph, then removes it, so the document keeps its content.
The check with Word closed quits Word, so it skips when Word has open documents.
"""

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from enum import Enum
from types import TracebackType
from typing import Self

import pytest

from spsync.mdparse import parse_body
from spsync.reader import join_items, read_items
from spsync.word import WordBackend

DOCUMENT_URL_VARIABLE = "SPSYNC_TEST_SHAREPOINT_URL"
WORD_BUNDLE_ID = "com.microsoft.Word"
FINDER_BUNDLE_ID = "com.apple.finder"
FRONT_POLL_SECONDS = 0.2
STATE_TIMEOUT_SECONDS = 30
# `lsappinfo info -only bundleid` prints one line such as "CFBundleIdentifier"="com.apple.finder".
BUNDLE_ID_LINE = re.compile(r'="([^"]+)"\s*$')


class WordState(Enum):
    CLOSED = "closed"
    FRONT = "front"
    BACKGROUND = "background"


def front_app() -> str:
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, check=True).stdout.strip()
    info = subprocess.run(
        ["lsappinfo", "info", "-only", "bundleid", asn], capture_output=True, text=True, check=True
    ).stdout
    match = BUNDLE_ID_LINE.search(info)
    return match.group(1) if match else ""


def word_running() -> bool:
    found = subprocess.run(
        ["lsappinfo", "find", f"bundleid={WORD_BUNDLE_ID}"], capture_output=True, text=True, check=True
    )
    return bool(found.stdout.strip())


def word_document_count() -> int:
    out = subprocess.run(
        ["osascript", "-e", f'tell application id "{WORD_BUNDLE_ID}" to count documents'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(out.strip())


def wait_for(condition: Callable[[], bool], what: str) -> None:
    deadline = time.time() + STATE_TIMEOUT_SECONDS
    while not condition():
        if time.time() > deadline:
            pytest.fail(f"Timed out waiting for {what}.")
        time.sleep(FRONT_POLL_SECONDS)


def prepare(state: WordState) -> str:
    """Put Word in `state` and return the bundle ID of the app that must stay in front."""
    if state is WordState.CLOSED:
        if word_running():
            if word_document_count():
                pytest.skip("Word has open documents. Close them before this check quits Word.")
            subprocess.run(["osascript", "-e", f'tell application id "{WORD_BUNDLE_ID}" to quit'], check=True)
            wait_for(lambda: not word_running(), "Word to quit")
    elif state is WordState.FRONT:
        subprocess.run(["open", "-b", WORD_BUNDLE_ID], check=True)
        wait_for(lambda: front_app() == WORD_BUNDLE_ID, "Word to come to the front")
    else:
        subprocess.run(["open", "-g", "-b", WORD_BUNDLE_ID], check=True)
        wait_for(word_running, "Word to start")
        subprocess.run(["open", "-b", FINDER_BUNDLE_ID], check=True)
        wait_for(lambda: front_app() == FINDER_BUNDLE_ID, "Finder to come to the front")
    return front_app()


class FrontAppWatch:
    """Records every app that is in front while the block runs."""

    def __init__(self) -> None:
        self.fronts: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while not self._stop.is_set():
            self.fronts.add(front_app())
            time.sleep(FRONT_POLL_SECONDS)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._stop.set()
        self._thread.join()


@pytest.fixture
def document_url() -> str:
    url = os.environ.get(DOCUMENT_URL_VARIABLE)
    if not url:
        pytest.skip(f"Set {DOCUMENT_URL_VARIABLE} to a SharePoint test document that OneDrive does not sync.")
    return url


@pytest.mark.integration
@pytest.mark.parametrize("state", list(WordState), ids=lambda s: s.value)
def test_pull_and_push_keep_the_foreground_app(state: WordState, document_url: str) -> None:
    expected_front = prepare(state)
    word = WordBackend()
    marker = f"spsync focus check {time.time_ns()}"
    with FrontAppWatch() as watch:
        name, original = word.fetch(document_url)
        original_note = join_items(read_items(original))
        _, saved = word.apply(
            name,
            original,
            read_items(original),
            parse_body(original_note.rstrip("\n") + f"\n\n{marker}\n"),
            suggest=False,
            dry_run=False,
        )
        assert saved is not None
        _, pushed = word.fetch(name)
        _, restored_copy = word.apply(
            name, pushed, read_items(pushed), parse_body(original_note), suggest=False, dry_run=False
        )
        assert restored_copy is not None
        _, restored = word.fetch(name)
    assert watch.fronts == {expected_front}
    assert marker in join_items(read_items(pushed))
    assert join_items(read_items(restored)) == original_note
