"""Manages config files and data storage locations.

- Config files (account/hashtag lists, taste profile, etc.): ~/.config/yunoballizer/
- App data root: ~/.local/share/yunoballizer/
  - Collected content: ~/.local/share/yunoballizer/sources/
  - Logs: ~/.local/share/yunoballizer/logs/
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "yunoballizer"
DATA_DIR = Path.home() / ".local" / "share" / "yunoballizer" / "sources"
LOG_DIR = Path.home() / ".local" / "state" / "yunoballizer" / "logs"

TEMPLATE_FILES = [
    "instagram/accounts.txt",
    "instagram/hashtags.txt",
    "tiktok/accounts.txt",
    "youtube/accounts.txt",
    "youtube/hashtags.txt",
    "urls.txt"
]


def ensure_config() -> None:
    """Create config/log directories and populate missing config files with default templates."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

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
    with path.open("a", encoding="utf-8") as f:
        f.write(value + "\n")
    return True
