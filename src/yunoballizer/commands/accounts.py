"""View and edit per-platform account IDs in inputs.json."""
from __future__ import annotations

from .. import config

PLATFORMS = ("instagram", "tiktok", "youtube")


def _validate_platform(platform: str) -> None:
    if platform not in PLATFORMS:
        raise SystemExit(f"Unknown platform '{platform}'. Choose from: {', '.join(PLATFORMS)}")


def _normalize(username: str) -> str:
    username = username.strip().lstrip("@").lower()
    if not username:
        raise SystemExit("Username cannot be empty.")
    return username


def list_accounts(platform: str | None = None) -> dict[str, list[str]]:
    """Return monitored accounts, keyed by platform (all platforms if none given)."""
    platforms = [platform] if platform else list(PLATFORMS)
    for name in platforms:
        _validate_platform(name)
    inputs = config.read_inputs()
    return {name: inputs[name] for name in platforms}


def add(platform: str, username: str) -> bool:
    """Add a normalized account ID. Returns True if it was newly added."""
    _validate_platform(platform)
    return config.add_input(platform, _normalize(username))


def remove(platform: str, username: str) -> bool:
    """Stop monitoring a normalized account ID."""
    _validate_platform(platform)
    return config.remove_input(platform, _normalize(username))
