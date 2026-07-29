"""Anonymous TikTok account harvesting (hashtag/trending discovery not supported)."""
from __future__ import annotations

import logging
import time

from . import config
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.tiktok")


def harvest(sleep_seconds: int = 15) -> None:
    accounts = config.read_lines("tiktok_accounts.txt")
    if not accounts:
        logger.info("tiktok_accounts.txt is empty, skipping")
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
            {"playlistend": 20},
        )
        time.sleep(sleep_seconds)
