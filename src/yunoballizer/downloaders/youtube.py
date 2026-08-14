"""Anonymous harvesting of YouTube Shorts channels."""
from __future__ import annotations

import logging

from .. import config
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.youtube")


def harvest(limit: int = 20, accounts: list[str] | None = None, skip: int = 0) -> None:
    out_dir = config.DATA_DIR / "youtube"
    archive = out_dir / "archive.txt"

    if accounts is None:
        accounts = config.read_lines(config.CONFIG_DIR / "youtube" / "accounts.txt")

    for channel in accounts:
        url = channel if channel.startswith("http") else f"https://www.youtube.com/{channel}"
        shorts_url = url.rstrip("/") + "/shorts"
        logger.info("[channel] checking %s...", shorts_url)
        download(
            shorts_url,
            str(out_dir / "channels" / "%(uploader)s" / "%(id)s.%(ext)s"),
            archive,
            {"playliststart": skip + 1, "playlistend": skip + limit},
        )
