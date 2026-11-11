"""Microsoft identity sign-in with a token cache kept in the macOS Keychain."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import msal

# Microsoft Graph Command Line Tools, a Microsoft-published public client. Override with
# SPSYNC_CLIENT_ID or config.json if your tenant requires its own app registration.
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
SCOPES = ["Files.ReadWrite.All", "Sites.Read.All", "User.Read"]
# Microsoft first-party public clients that tenants usually trust already. They only accept
# their preauthorized permissions, so request ".default" and sign in with a device code.
PRESETS = {
    "office": "d3590ed6-52b3-4102-aeff-aad2292ab01c",
    "teams": "1fec8e78-bce4-4aaf-ab1b-5451cc387264",
}
DEFAULT_SCOPE = ["https://graph.microsoft.com/.default"]
CONFIG_DIR = Path(os.environ.get("SPSYNC_CONFIG_DIR", Path.home() / ".config" / "spsync"))


class AuthError(Exception):
    pass


def load_config() -> dict:
    path = CONFIG_DIR / "config.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / "config.json"
    path.write_text(json.dumps(cfg, indent=2))
    path.chmod(0o600)


def _cache():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    location = str(CONFIG_DIR / "token_cache.bin")
    try:
        from msal_extensions import PersistedTokenCache, build_encrypted_persistence

        return PersistedTokenCache(build_encrypted_persistence(location))
    except Exception as exc:  # noqa: BLE001 - fall back to a private file cache
        from msal_extensions import FilePersistence, PersistedTokenCache

        print(f"spsync: keychain unavailable ({exc}); using a private file token cache.", file=sys.stderr)
        persistence = FilePersistence(location)
        cache = PersistedTokenCache(persistence)
        Path(location).touch(mode=0o600, exist_ok=True)
        return cache


class Auth:
    def __init__(self):
        cfg = load_config()
        self.client_id = os.environ.get("SPSYNC_CLIENT_ID") or cfg.get("client_id") or DEFAULT_CLIENT_ID
        self.client_id = PRESETS.get(self.client_id, self.client_id)
        self.scopes = SCOPES if self.client_id == DEFAULT_CLIENT_ID else DEFAULT_SCOPE
        self.device_only = self.client_id in PRESETS.values()
        tenant = os.environ.get("SPSYNC_TENANT") or cfg.get("tenant") or "organizations"
        self.app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{tenant}",
            token_cache=_cache(),
        )

    def account(self):
        accounts = self.app.get_accounts()
        return accounts[0] if accounts else None

    def login(self, device: bool = False) -> dict:
        if device or self.device_only:
            flow = self.app.initiate_device_flow(scopes=self.scopes)
            if "user_code" not in flow:
                raise AuthError(flow.get("error_description", "Could not start device sign-in."))
            print(flow["message"], file=sys.stderr, flush=True)
            result = self.app.acquire_token_by_device_flow(flow)
        else:
            print("Opening a browser to sign in. If it asks for admin approval, your tenant needs IT consent; press Ctrl-C.", file=sys.stderr, flush=True)
            result = self.app.acquire_token_interactive(scopes=self.scopes, prompt="select_account", timeout=180)
        if "access_token" not in result:
            raise AuthError(result.get("error_description") or result.get("error") or "Sign-in failed.")
        return result

    def token(self, force_refresh: bool = False) -> str:
        acct = self.account()
        if acct is None:
            raise AuthError("Not signed in. Run: spsync login")
        result = self.app.acquire_token_silent(self.scopes, account=acct, force_refresh=force_refresh)
        if not result or "access_token" not in result:
            raise AuthError("Session expired. Run: spsync login")
        return result["access_token"]

    def logout(self):
        for acct in self.app.get_accounts():
            self.app.remove_account(acct)
