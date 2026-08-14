"""Anonymous harvesting of YouTube accounts' Shorts."""
from __future__ import annotations

import logging

from .. import config, storage
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.youtube")


def harvest(limit: int = 20, accounts: list[str] | None = None, skip: int = 0) -> None:
    out_dir = config.SOURCES_DIR / "youtube"
    archive = config.ARCHIVE_DIR / "youtube.txt"

    if accounts is None:
        accounts = config.read_lines(config.CONFIG_DIR / "youtube" / "accounts.txt")

    for account in accounts:
        url = account if account.startswith("http") else f"https://www.youtube.com/{account}"
        shorts_url = url.rstrip("/") + "/shorts"
        logger.info("[account] checking %s...", shorts_url)
        download(
            shorts_url,
            str(out_dir / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
            archive,
            {"playliststart": skip + 1, "playlistend": skip + limit},
            metadata_template=str(out_dir / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
            caption_template=str(out_dir / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
        )

    storage.organize_ytdlp_tree(out_dir)
