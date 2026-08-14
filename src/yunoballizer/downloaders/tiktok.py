"""Anonymous TikTok account harvesting (hashtag/trending discovery not supported)."""
from __future__ import annotations

import logging
import time

from .. import config
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.tiktok")


def harvest(
    sleep_seconds: int = 15,
    limit: int = 20,
    accounts: list[str] | None = None,
    skip: int = 0,
) -> None:
    if accounts is None:
        accounts_file = config.CONFIG_DIR / "tiktok" / "accounts.txt"
        accounts = config.read_lines(accounts_file)
        if not accounts:
            logger.info("%s is empty, skipping", accounts_file)
            return

    out_dir = config.DATA_DIR / "tiktok"
    archive = out_dir / "archive.txt"

    for account in accounts:
        url = f"https://www.tiktok.com/@{account}"
        logger.info("[account] checking %s...", url)
        download(
            url,
            str(out_dir / "accounts" / account / "%(id)s.%(ext)s"),
            archive,
            {"playliststart": skip + 1, "playlistend": skip + limit},
        )
        time.sleep(sleep_seconds)
