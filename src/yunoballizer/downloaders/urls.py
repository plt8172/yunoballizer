"""Batch download of individual URLs (TikTok/YouTube/etc.) listed in urls.txt."""
from __future__ import annotations

import logging

from .. import config, storage
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.urls")


def harvest() -> None:
    urls_file = config.CONFIG_DIR / "urls.txt"
    urls = config.read_lines(urls_file)
    if not urls:
        logger.info("%s is empty, skipping", urls_file)
        return

    out_dir = config.SOURCES_DIR / "other"
    archive = config.ARCHIVE_DIR / "other.txt"
    logger.info("Processing %d URL(s)...", len(urls))
    download(
        urls,
        str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
        archive,
        metadata_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
        caption_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
    )

    storage.organize_ytdlp_tree(out_dir)
