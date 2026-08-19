"""Anonymous TikTok account harvesting (hashtag/trending discovery not supported)."""
from __future__ import annotations

import logging
import time
from datetime import date

from .. import config, storage
from .budget import TotalBudget
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.tiktok")


def harvest(
    sleep_seconds: int = 15,
    limit: int = 20,
    accounts: list[str] | None = None,
    skip: int = 0,
    since: date | None = None,
    until: date | None = None,
    media_type: str | None = None,
    budget: TotalBudget | None = None,
) -> None:
    if media_type == "photo":
        logger.info("TikTok posts are always video; skipping for --type photo.")
        return

    if accounts is None:
        accounts_file = config.CONFIG_DIR / "tiktok" / "accounts.txt"
        accounts = config.read_lines(accounts_file)
        if not accounts:
            logger.info("%s is empty, skipping", accounts_file)
            return

    out_dir = config.SOURCES_DIR / "tiktok"
    archive = config.ARCHIVE_DIR / "tiktok.txt"

    date_opts = {}
    if since is not None:
        date_opts["dateafter"] = since.strftime("%Y%m%d")
    if until is not None:
        date_opts["datebefore"] = until.strftime("%Y%m%d")

    for account in accounts:
        if budget is not None and budget.exhausted:
            logger.info("Total download limit reached; stopping.")
            break
        account_limit = budget.take(limit) if budget is not None else limit
        if account_limit <= 0:
            continue

        url = f"https://www.tiktok.com/@{account}"
        logger.info("[account] checking %s...", url)
        download(
            url,
            str(out_dir / account / "%(id)s" / "video.%(ext)s"),
            archive,
            {"playliststart": skip + 1, "playlistend": skip + account_limit, **date_opts},
            metadata_template=str(out_dir / account / "%(id)s" / "metadata.%(ext)s"),
            caption_template=str(out_dir / account / "%(id)s" / "caption.%(ext)s"),
            on_item_done=storage.refresh_new_ytdlp_post,
        )
        time.sleep(sleep_seconds)

    storage.organize_ytdlp_tree(out_dir)
