"""Batch download of individual URLs (TikTok/YouTube/Instagram/etc.) listed in urls.txt."""
from __future__ import annotations

import logging

from .. import config, storage
from . import instagram
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.urls")


def harvest() -> None:
    urls_file = config.CONFIG_DIR / "urls.txt"
    all_urls = config.read_lines(urls_file)
    if not all_urls:
        logger.info("%s is empty, skipping", urls_file)
        return

    # Instagram URLs are routed through Instaloader instead of yt-dlp: yt-dlp's
    # Instagram extractor can't download photo posts at all and has been
    # unreliable for video (see instagram.harvest_urls's docstring).
    instagram_urls: list[str] = []
    other_urls: list[str] = []
    for url in all_urls:
        (instagram_urls if instagram.is_instagram_url(url) else other_urls).append(url)

    if instagram_urls:
        logger.info("Processing %d Instagram URL(s)...", len(instagram_urls))
        instagram.harvest_urls(instagram_urls)

    if not other_urls:
        return

    out_dir = config.SOURCES_DIR / "other"
    archive = config.ARCHIVE_DIR / "other.txt"
    logger.info("Processing %d URL(s)...", len(other_urls))
    download(
        other_urls,
        str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
        archive,
        metadata_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
        caption_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
        on_item_done=storage.refresh_new_ytdlp_post,
    )

    storage.organize_ytdlp_tree(out_dir)
