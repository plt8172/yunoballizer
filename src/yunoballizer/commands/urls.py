"""View and edit persistent URLs in inputs.json."""
from __future__ import annotations

from urllib.parse import urlsplit

from .. import config


def _normalize(url: str) -> str:
    url = url.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"Invalid URL {url!r}: expected a full http(s):// URL.")
    return url


def list_urls() -> list[str]:
    return config.input_values("urls")


def add(url: str) -> bool:
    """Persist a URL. Returns True only when it was newly added."""
    return config.add_input("urls", _normalize(url))


def remove(url: str) -> bool:
    """Remove an exact URL."""
    return config.remove_input("urls", _normalize(url))
