"""Anonymous harvesting of YouTube Shorts channels/hashtags."""
from __future__ import annotations

import logging

from .. import config
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.youtube")


def harvest() -> None:
    out_dir = config.DATA_DIR / "youtube"
    archive = out_dir / "archive.txt"

    for channel in config.read_lines(config.CONFIG_DIR / "youtube" / "accounts.txt"):
        url = channel if channel.startswith("http") else f"https://www.youtube.com/{channel}"
        shorts_url = url.rstrip("/") + "/shorts"
        logger.info("[channel] checking %s...", shorts_url)
        download(
            shorts_url,
            str(out_dir / "channels" / "%(uploader)s" / "%(id)s.%(ext)s"),
            archive,
            {"playlistend": 20},
        )

    for tag in config.read_lines(config.CONFIG_DIR / "youtube" / "hashtags.txt"):
        url = f"https://www.youtube.com/hashtag/{tag}"
        logger.info("[hashtag] checking #%s...", tag)
        download(
            url,
            str(out_dir / "hashtags" / tag / "%(id)s.%(ext)s"),
            archive,
            {"playlistend": 20},
        )
