"""spsync: edit SharePoint Word documents as Obsidian notes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote

from . import config
from .auth import Auth, AuthError
from .core import Session, SyncError
from .doctor import SetupEnvironment, cli_version, complete, run_checks
from .graph import Graph, GraphError
from .local import LOCAL, WORD, backend
from .mdparse import split_frontmatter

LAST_SEARCH = config.CONFIG_DIR / "last_search.json"
FILE_URL_PREFIX = "file://"
WATCH_TICK_SECONDS = 5
EXIT_ERROR = 1
EXIT_CONFLICT = 2
EXIT_SETUP_INCOMPLETE = 3
EXIT_INTERRUPTED = 130


def _vault(args: argparse.Namespace) -> Path:
    """The vault from --vault, then SPSYNC_VAULT, then the current folder."""
    if args.vault:
        return Path(args.vault).expanduser()
    return config.default_vault()


def _session_for_note(note: Path) -> Session:
    return Session.for_path(note)


def cmd_login(args: argparse.Namespace) -> None:
    auth = Auth()
    auth.login(device=args.device)
    me = Graph(auth).me()
    print(f"Signed in as {me.get('displayName')} <{me.get('mail') or me.get('userPrincipalName')}>")


def cmd_mode(args: argparse.Namespace) -> None:
    cfg = config.load_config()
    if args.mode:
        cfg["backend"] = args.mode
        config.save_config(cfg)
    if args.author:
        cfg["author"] = args.author
        config.save_config(cfg)
    if args.root:
        cfg["roots"] = [str(Path(r).expanduser()) for r in args.root]
        config.save_config(cfg)
    b = backend()
    if args.json:
        print(json.dumps({"backend": b.mode, "author": b.local.author, "roots": [str(r) for r in b.local.roots]}))
        return
    print(f"backend: {b.mode}")
    if b.mode == LOCAL:
        print(f"author:  {b.local.author}")
        for r in b.local.roots:
            print(f"root:    {r}")


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_checks(SetupEnvironment.from_system())
    ok = complete(checks)
    if args.json:
        print(json.dumps({"complete": ok, "checks": [asdict(c) for c in checks]}))
    else:
        for c in checks:
            optional = "" if c.required or c.ok else " (optional)"
            print(f"{'pass' if c.ok else 'fail'}  {c.name}{optional}: {c.detail}")
            if c.fix:
                print(f"      Fix: {c.fix}")
    return 0 if ok else EXIT_SETUP_INCOMPLETE


def cmd_logout(args: argparse.Namespace) -> None:
    Auth().logout()
    print("Signed out.")


def cmd_whoami(args: argparse.Namespace) -> None:
    me = backend().me()
    print(f"{me.get('displayName')} <{me.get('mail') or me.get('userPrincipalName')}>")


def _print_hits(hits: list[dict], *, as_json: bool = False) -> None:
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "ref": f"{(h.get('parentReference') or {}).get('driveId', '')}:{h.get('id')}",
                        "name": h.get("name"),
                        "webUrl": h.get("webUrl"),
                        "modified": (h.get("lastModifiedDateTime") or "")[:10],
                        "by": ((h.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", ""),
                    }
                    for h in hits
                ]
            )
        )
        return
    saved = []
    for n, h in enumerate(hits, 1):
        drive = (h.get("parentReference") or {}).get("driveId", "")
        ref = f"{drive}:{h.get('id')}"
        who = ((h.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", "")
        when = (h.get("lastModifiedDateTime") or "")[:10]
        print(f"{n:>2}. {h.get('name')}  ({when} {who})")
        print(f"    {h.get('webUrl')}")
        saved.append(ref)
    LAST_SEARCH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SEARCH.write_text(json.dumps(saved))
    if hits:
        print("\nPull one with: spsync pull <number>")


def cmd_search(args: argparse.Namespace) -> None:
    _print_hits(backend().search(" ".join(args.query), size=args.limit), as_json=args.json)


def cmd_recent(args: argparse.Namespace) -> None:
    _print_hits(backend().recent()[: args.limit], as_json=args.json)


def _expand_ref(ref: str) -> str:
    if ref.isdigit() and LAST_SEARCH.exists():
        saved = json.loads(LAST_SEARCH.read_text())
        k = int(ref) - 1
        if 0 <= k < len(saved):
            return saved[k]
    return ref


def cmd_pull(args: argparse.Namespace) -> None:
    vault = _vault(args)
    out = Path(args.out).expanduser() if args.out else None
    session = Session.for_path(out.parent if out else vault)
    note = session.pull(_expand_ref(args.ref), out=out, force=args.force)
    print(f"Pulled to {note}")


def _notes(args: argparse.Namespace) -> list[Path]:
    if args.all:
        vault = _vault(args)
        s = Session.for_path(vault)
        return [s.vault / b.note for b in s.store.all() if (s.vault / b.note).exists()]
    if not args.notes:
        raise SyncError("Name one or more notes, or pass --all.")
    return [Path(n).expanduser() for n in args.notes]


def cmd_push(args: argparse.Namespace) -> None:
    for note in _notes(args):
        res = _session_for_note(note).push(note, suggest=args.suggest, dry_run=args.dry_run)
        print(f"{note.name}: {res.status}. {res.message}")


def cmd_sync(args: argparse.Namespace) -> int:
    rc = 0
    for note in _notes(args):
        try:
            res = _session_for_note(note).sync(note, suggest=args.suggest)
            print(f"{note.name}: {res.status}. {res.message}")
            if res.status == "conflict":
                rc = EXIT_CONFLICT
        except (SyncError, GraphError) as exc:
            print(f"{note.name}: error. {exc}", file=sys.stderr)
            rc = EXIT_ERROR
    return rc


def cmd_new(args: argparse.Namespace) -> None:
    note = Path(args.note).expanduser()
    res = _session_for_note(note).new(note, _expand_ref(args.folder), args.name, suggest=False)
    print(res.message)


def cmd_status(args: argparse.Namespace) -> None:
    vault = _vault(args)
    s = Session.for_path(vault)
    bindings = s.store.all()
    if not bindings:
        print(f"No linked notes in {s.vault}.")
        return
    for b in bindings:
        note = s.vault / b.note
        if not note.exists():
            print(f"missing   {b.note}")
            continue
        local, _ = s.local_changed(b, note)
        remote = ""
        if args.remote:
            try:
                remote = " remote-changed" if s.graph.item(b.drive_id, b.item_id).get("eTag") != b.etag else ""
            except GraphError as exc:
                remote = f" ({exc.status})"
        print(f"{'edited ' if local else 'clean  '}{remote:>15}  {b.note}")


def cmd_open(args: argparse.Namespace) -> None:
    note = Path(args.note).expanduser()
    fm, _ = split_frontmatter(note.read_text())
    url = fm.get("sharepoint")
    if url and url.startswith(FILE_URL_PREFIX):
        url = unquote(url[len(FILE_URL_PREFIX) :])
    if not url:
        raise SyncError("This note has no `sharepoint` link.")
    subprocess.run(["open", url], check=False)


def cmd_unlink(args: argparse.Namespace) -> None:
    note = Path(args.note).expanduser()
    s = _session_for_note(note)
    b, _ = s.binding_for(note)
    s.store.remove(b.ref)
    print(f"Unlinked {note.name}. The note and the SharePoint document are untouched.")


def cmd_watch(args: argparse.Namespace) -> None:
    vault = _vault(args)
    s = Session.for_path(vault)
    last_remote: dict[str, float] = {}
    print(
        f"Watching {s.vault} (remote every {args.interval}s, push after {args.idle}s idle). Ctrl-C to stop.", flush=True
    )
    while True:
        for b in s.store.all():
            note = s.vault / b.note
            if not note.exists():
                continue
            now = time.time()
            try:
                local, _ = s.local_changed(b, note)
                if local and now - note.stat().st_mtime < args.idle:
                    continue
                remote_due = now - last_remote.get(b.ref, 0) >= args.interval and b.drive_id != WORD
                if local or remote_due:
                    last_remote[b.ref] = now
                    res = s.sync(note, suggest=args.suggest)
                    if res.status != "unchanged":
                        print(f"{time.strftime('%H:%M:%S')} {b.note}: {res.status}. {res.message}", flush=True)
            except (SyncError, GraphError, AuthError) as exc:
                print(f"{time.strftime('%H:%M:%S')} {b.note}: error. {exc}", file=sys.stderr, flush=True)
        time.sleep(WATCH_TICK_SECONDS)


def _add_account_commands(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("login", help="Sign in to Microsoft 365")
    s.add_argument("--device", action="store_true", help="Use a device code instead of a browser window")
    s.set_defaults(fn=cmd_login)
    sub.add_parser("logout", help="Forget cached tokens").set_defaults(fn=cmd_logout)
    s = sub.add_parser("mode", help="Show or set the backend (local OneDrive files, or Graph)")
    s.add_argument("mode", nargs="?", choices=["local", "graph"])
    s.add_argument("--author", help="Name used on comments and tracked changes in local mode")
    s.add_argument("--root", action="append", help="Folder to search for synced docs (repeatable)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_mode)
    sub.add_parser("whoami", help="Show the signed-in account").set_defaults(fn=cmd_whoami)
    s = sub.add_parser("doctor", help="Check first-run setup and show how to fix each problem")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)


def _add_discovery_commands(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("search", help="Find Word documents across SharePoint and OneDrive")
    s.add_argument("query", nargs="+")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("recent", help="List Word documents you used recently")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_recent)


def _add_sync_commands(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("pull", help="Download a document into the vault as a note")
    s.add_argument("ref", help="SharePoint link, driveId:itemId, or a number from the last search")
    s.add_argument("--out", help="Note path (default: <vault>/SharePoint/<name>.md)")
    s.add_argument("--vault")
    s.add_argument("--force", action="store_true", help="Overwrite local edits")
    s.set_defaults(fn=cmd_pull)

    for name, fn, helptext in (
        ("push", cmd_push, "Send note edits to SharePoint"),
        ("sync", cmd_sync, "Pull, merge, and push as needed"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("notes", nargs="*")
        s.add_argument("--all", action="store_true", help="Every linked note in the vault")
        s.add_argument("--vault")
        s.add_argument("--suggest", action="store_true", help="Send edits as tracked changes")
        if name == "push":
            s.add_argument("--dry-run", action="store_true", help="Show what would change without uploading")
        s.set_defaults(fn=fn)


def _add_note_commands(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("new", help="Create a new Word document in SharePoint from a note")
    s.add_argument("note")
    s.add_argument("--folder", required=True, help="Folder link, or `me` for your OneDrive root")
    s.add_argument("--name", help="File name (default: note name)")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("status", help="Show linked notes and local edits")
    s.add_argument("--vault")
    s.add_argument("--remote", action="store_true", help="Also check SharePoint for newer versions")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("open", help="Open the document in the browser")
    s.add_argument("note")
    s.set_defaults(fn=cmd_open)

    s = sub.add_parser("unlink", help="Stop syncing a note")
    s.add_argument("note")
    s.set_defaults(fn=cmd_unlink)

    s = sub.add_parser("watch", help="Keep linked notes in sync until stopped")
    s.add_argument("--vault")
    s.add_argument("--interval", type=int, default=60, help="Seconds between SharePoint checks")
    s.add_argument("--idle", type=int, default=20, help="Seconds a note must be idle before pushing")
    s.add_argument("--suggest", action="store_true")
    s.set_defaults(fn=cmd_watch)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spsync", description="Edit SharePoint Word documents as Obsidian notes.")
    p.add_argument("--version", action="version", version=f"%(prog)s {cli_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)
    _add_account_commands(sub)
    _add_discovery_commands(sub)
    _add_sync_commands(sub)
    _add_note_commands(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
        return rc or 0
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except (SyncError, GraphError, AuthError) as exc:
        print(f"spsync: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
