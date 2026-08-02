"""Batch download of individual URLs (TikTok/YouTube/etc.) listed in urls.txt."""
from __future__ import annotations

import logging

from .. import config
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.urls")


def harvest() -> None:
    urls_file = config.CONFIG_DIR / "urls.txt"
    urls = config.read_lines(urls_file)
    if not urls:
        logger.info("%s is empty, skipping", urls_file)
        return

    out_dir = config.DATA_DIR / "other"
    archive = out_dir / "archive.txt"
    logger.info("Processing %d URL(s)...", len(urls))
    download(
        urls,
        str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s.%(ext)s"),
        archive,
    )
