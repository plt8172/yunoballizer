"""Anonymous harvesting of YouTube accounts' Shorts."""
from __future__ import annotations

import functools
import logging
import time
from datetime import date

import yt_dlp

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
    progress: storage.ReviewProgress | None = None,
) -> None:
    if media_type == "photo":
        logger.info("YouTube Shorts are always video; skipping for --type photo.")
        return
    progress = progress if progress is not None else storage.ReviewProgress()

    out_dir = config.DOWNLOADED_DIR / "youtube"

    if accounts is None:
        accounts = config.input_values("youtube")

    date_opts = {}
    if since is not None or until is not None:
        date_opts["daterange"] = yt_dlp.utils.DateRange(
            start=since.strftime("%Y%m%d") if since is not None else None,
            end=until.strftime("%Y%m%d") if until is not None else None,
        )

    for account in accounts:
        if budget is not None and budget.exhausted:
            logger.info("Total download limit reached; stopping.")
            break
        account_limit = budget.take(limit) if budget is not None else limit
        if account_limit <= 0:
            continue

        account_id = account.lstrip("@")
        url = f"https://www.youtube.com/@{account_id}"
        shorts_url = url.rstrip("/") + "/shorts"
        logger.info("[account] checking %s...", shorts_url)
        download(
            shorts_url,
            str(out_dir / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
            {"playliststart": skip + 1, "playlistend": skip + account_limit, **date_opts},
            metadata_template=str(out_dir / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
            caption_template=str(out_dir / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
            on_item_done=functools.partial(storage.refresh_new_ytdlp_post, progress=progress),
        )
        if sleep_seconds:
            time.sleep(sleep_seconds)

    storage.organize_ytdlp_tree(out_dir)
