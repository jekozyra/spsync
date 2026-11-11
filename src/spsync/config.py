"""User settings: `SPSYNC_*` environment variables and `config.json` in the configuration folder.

Every other module reads settings through this module. An environment variable wins over `config.json`,
except for search roots, where `config.json` wins so that `spsync mode --root` takes effect.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict

CONFIG_DIR = Path(os.environ.get("SPSYNC_CONFIG_DIR", Path.home() / ".config" / "spsync"))
CONFIG_FILE_MODE = 0o600

# Microsoft Graph Command Line Tools, a Microsoft-published public client. Override it with
# SPSYNC_CLIENT_ID or config.json if your tenant requires its own app registration.
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
DEFAULT_TENANT = "organizations"
DEFAULT_AUTHOR = "spsync"


class Settings(TypedDict, total=False):
    """The keys that `config.json` can hold. Every key is optional."""

    backend: str
    author: str
    roots: list[str]
    client_id: str
    tenant: str


def load_config() -> Settings:
    path = CONFIG_DIR / "config.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_config(cfg: Settings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / "config.json"
    path.write_text(json.dumps(cfg, indent=2))
    path.chmod(CONFIG_FILE_MODE)


def client_id() -> str:
    return os.environ.get("SPSYNC_CLIENT_ID") or load_config().get("client_id") or DEFAULT_CLIENT_ID


def tenant() -> str:
    return os.environ.get("SPSYNC_TENANT") or load_config().get("tenant") or DEFAULT_TENANT


def backend_mode() -> str | None:
    """The configured backend name, or None when the caller should use its default."""
    return os.environ.get("SPSYNC_BACKEND") or load_config().get("backend")


def configured_roots() -> list[Path] | None:
    """Search roots from `config.json` or `SPSYNC_ROOTS`, or None when neither sets them."""
    roots = load_config().get("roots")
    if roots:
        return [Path(r).expanduser() for r in roots]
    env = os.environ.get("SPSYNC_ROOTS")
    if env:
        return [Path(r).expanduser() for r in env.split(os.pathsep) if r]
    return None


def configured_author() -> str | None:
    return load_config().get("author")


def login_name() -> str:
    """The macOS login name, the last fallback for the comment author."""
    return os.environ.get("USER", DEFAULT_AUTHOR)


def default_vault() -> Path:
    env = os.environ.get("SPSYNC_VAULT")
    return Path(env).expanduser() if env else Path.cwd()
