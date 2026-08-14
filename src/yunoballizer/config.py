"""Manages user-editable configuration and application storage locations.

Follows the XDG Base Directory conventions:

- Data:   $YUNOBALLIZER_DATA_DIR, else $XDG_DATA_HOME/yunoballizer, else ~/.local/share/yunoballizer
- Config: $XDG_CONFIG_HOME/yunoballizer, else ~/.config/yunoballizer
- State:  $XDG_STATE_HOME/yunoballizer, else ~/.local/state/yunoballizer

A relative path in any of these environment variables is rejected outright
(rather than silently falling back) so a typo doesn't quietly redirect where
content is saved.
"""
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise SystemExit(f"{name} must be an absolute path, got: {value!r}")
    return path


def _data_root() -> Path:
    override = _env_path("YUNOBALLIZER_DATA_DIR")
    if override is not None:
        return override
    xdg_data_home = _env_path("XDG_DATA_HOME")
    if xdg_data_home is not None:
        return xdg_data_home / "yunoballizer"
    return Path.home() / ".local" / "share" / "yunoballizer"


def _config_root() -> Path:
    xdg_config_home = _env_path("XDG_CONFIG_HOME")
    if xdg_config_home is not None:
        return xdg_config_home / "yunoballizer"
    return Path.home() / ".config" / "yunoballizer"


def _state_root() -> Path:
    xdg_state_home = _env_path("XDG_STATE_HOME")
    if xdg_state_home is not None:
        return xdg_state_home / "yunoballizer"
    return Path.home() / ".local" / "state" / "yunoballizer"


DATA_DIR = _data_root()
CONFIG_DIR = _config_root()
STATE_DIR = _state_root()

SOURCES_DIR = DATA_DIR / "sources"
REVIEW_DIR = DATA_DIR / "review"
CURATED_DIR = DATA_DIR / "curated"
DERIVED_DIR = DATA_DIR / "derived"

ARCHIVE_DIR = STATE_DIR / "archives"
LOG_DIR = STATE_DIR / "logs"
CURATION_LOG_PATH = STATE_DIR / "curation_log.json"

TEMPLATE_FILES = [
    "instagram/accounts.txt",
    "tiktok/accounts.txt",
    "youtube/accounts.txt",
    "urls.txt",
]


def ensure_config() -> None:
    """Create config/data/state directories and populate missing config templates."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (SOURCES_DIR, REVIEW_DIR, CURATED_DIR, DERIVED_DIR, ARCHIVE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    for name in TEMPLATE_FILES:
        dest = CONFIG_DIR / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        try:
            content = (
                resources.files("yunoballizer.templates")
                .joinpath(name)
                .read_text(encoding="utf-8")
            )
        except Exception:
            content = ""
        dest.write_text(content, encoding="utf-8")


def read_lines(path: Path) -> list[str]:
    """Return non-comment, non-empty lines from a config file."""
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def append_line(path: Path, value: str) -> bool:
    """Append a value to a config file if not already present. Returns True if actually added."""
    existing = set(read_lines(path))
    if value in existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_leading_newline = False
    if path.exists():
        content = path.read_bytes()
        needs_leading_newline = bool(content) and not content.endswith(b"\n")
    with path.open("a", encoding="utf-8") as f:
        if needs_leading_newline:
            f.write("\n")
        f.write(value + "\n")
    return True
