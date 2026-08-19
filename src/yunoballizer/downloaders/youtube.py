"""Anonymous harvesting of YouTube accounts' Shorts."""
from __future__ import annotations

import logging
import time
from datetime import date

from .. import config, storage
from .budget import TotalBudget
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.youtube")


def harvest(
    limit: int = 20,
    accounts: list[str] | None = None,
    skip: int = 0,
    sleep_seconds: int = 0,
    since: date | None = None,
    until: date | None = None,
    media_type: str | None = None,
    budget: TotalBudget | None = None,
) -> None:
    if media_type == "photo":
        logger.info("YouTube Shorts are always video; skipping for --type photo.")
        return

    out_dir = config.SOURCES_DIR / "youtube"
    archive = config.ARCHIVE_DIR / "youtube.txt"

    if accounts is None:
        accounts = config.read_lines(config.CONFIG_DIR / "youtube" / "accounts.txt")

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

        url = account if account.startswith("http") else f"https://www.youtube.com/{account}"
        shorts_url = url.rstrip("/") + "/shorts"
        logger.info("[account] checking %s...", shorts_url)
        download(
            shorts_url,
            str(out_dir / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
            archive,
            {"playliststart": skip + 1, "playlistend": skip + account_limit, **date_opts},
            metadata_template=str(out_dir / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
            caption_template=str(out_dir / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
            on_item_done=storage.refresh_new_ytdlp_post,
        )
        if sleep_seconds:
            time.sleep(sleep_seconds)

    storage.organize_ytdlp_tree(out_dir)
