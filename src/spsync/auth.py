"""Microsoft identity sign-in with a token cache kept in the macOS Keychain."""

from __future__ import annotations

import sys
from pathlib import Path

import msal
from msal_extensions import FilePersistence, PersistedTokenCache, build_encrypted_persistence

from . import config

SCOPES = ["Files.ReadWrite.All", "Sites.Read.All", "User.Read"]
SIGN_IN_TIMEOUT_SECONDS = 180


class AuthError(Exception):
    pass


def _cache() -> PersistedTokenCache:
    """Keep tokens in the macOS Keychain, or in a private file when the Keychain is unavailable."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    location = str(config.CONFIG_DIR / "token_cache.bin")
    try:
        return PersistedTokenCache(build_encrypted_persistence(location))
    except (OSError, RuntimeError) as exc:
        print(f"spsync: keychain unavailable ({exc}); using a private file token cache.", file=sys.stderr)
        persistence = FilePersistence(location)
        cache = PersistedTokenCache(persistence)
        Path(location).touch(mode=0o600, exist_ok=True)
        return cache


class Auth:
    def __init__(self) -> None:
        self.client_id = config.client_id()
        tenant = config.tenant()
        self.app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{tenant}",
            token_cache=_cache(),
        )

    def account(self) -> dict | None:
        accounts = self.app.get_accounts()
        return accounts[0] if accounts else None

    def login(self, device: bool = False) -> dict:
        if device:
            flow = self.app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                raise AuthError(flow.get("error_description", "Could not start device sign-in."))
            print(flow["message"], file=sys.stderr, flush=True)
            result = self.app.acquire_token_by_device_flow(flow)
        else:
            print(
                "Opening a browser to sign in. If it asks for admin approval, your tenant needs IT consent; press Ctrl-C.",
                file=sys.stderr,
                flush=True,
            )
            result = self.app.acquire_token_interactive(
                scopes=SCOPES, prompt="select_account", timeout=SIGN_IN_TIMEOUT_SECONDS
            )
        if "access_token" not in result:
            raise AuthError(result.get("error_description") or result.get("error") or "Sign-in failed.")
        return result

    def token(self, force_refresh: bool = False) -> str:
        acct = self.account()
        if acct is None:
            raise AuthError("Not signed in. Run: spsync login")
        result = self.app.acquire_token_silent(SCOPES, account=acct, force_refresh=force_refresh)
        if not result or "access_token" not in result:
            raise AuthError("Session expired. Run: spsync login")
        return result["access_token"]

    def logout(self) -> None:
        for acct in self.app.get_accounts():
            self.app.remove_account(acct)
