"""View and edit the per-platform accounts.txt lists."""
from __future__ import annotations

from pathlib import Path

from .. import config

PLATFORMS = ("instagram", "tiktok", "youtube")


def accounts_file(platform: str) -> Path:
    if platform not in PLATFORMS:
        raise SystemExit(f"Unknown platform '{platform}'. Choose from: {', '.join(PLATFORMS)}")
    return config.CONFIG_DIR / platform / "accounts.txt"


def _normalize(username: str) -> str:
    username = username.strip().lstrip("@").lower()
    if not username:
        raise SystemExit("Username cannot be empty.")
    return username


def list_accounts(platform: str | None = None) -> dict[str, list[str]]:
    """Return monitored accounts, keyed by platform (all platforms if none given)."""
    platforms = [platform] if platform else list(PLATFORMS)
    return {p: config.read_lines(accounts_file(p)) for p in platforms}


def add(platform: str, username: str) -> bool:
    """Add an account to monitor. Returns True if it was actually added.

    Matches case-insensitively against whatever's already in the file --
    accounts.txt is meant to be hand-edited too, and a manually-typed
    "MrBeast" shouldn't end up duplicated by a later `accounts add
    youtube mrbeast`.
    """
    return config.append_line(accounts_file(platform), _normalize(username), case_insensitive=True)


def remove(platform: str, username: str) -> bool:
    """Stop monitoring an account. Returns True if it was actually removed.

    Case-insensitive for the same reason as add(): a hand-typed "MrBeast"
    must still be found by `accounts remove youtube mrbeast`.
    """
    return config.remove_line(accounts_file(platform), _normalize(username), case_insensitive=True)
