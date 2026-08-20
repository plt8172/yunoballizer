"""Download individual post URLs through one platform-aware entry point."""
from __future__ import annotations

import functools
import logging
import re

import instaloader

from .. import config, storage
from .budget import TotalBudget
from .instaloader_helper import new_loader, post_is_complete
from .ytdlp_helper import download

logger = logging.getLogger("yunoballizer.urls")
_INSTAGRAM_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def is_instagram_url(url: str) -> bool:
    return _INSTAGRAM_SHORTCODE_RE.search(url) is not None


def download_instagram_urls(
    urls: list[str], progress: storage.ReviewProgress | None = None
) -> None:
    """Download Instagram post URLs via Instaloader, including photo posts.

    yt-dlp's Instagram extractor does not support photo posts and has been
    unreliable for video, while Instaloader already handles both media types.
    """
    progress = progress if progress is not None else storage.ReviewProgress()
    out_dir = config.DOWNLOADED_DIR / "instagram"
    out_dir.mkdir(parents=True, exist_ok=True)
    loader = new_loader(out_dir)

    for url in urls:
        match = _INSTAGRAM_SHORTCODE_RE.search(url)
        if match is None:
            logger.error("Could not parse an Instagram shortcode from %s", url)
            continue
        shortcode = match.group(1)

        try:
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
        except instaloader.InstaloaderException as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            continue

        account_dir = out_dir / post.owner_username
        post_dir = account_dir / post.shortcode
        if post_is_complete(post_dir, post.mediacount):
            continue

        try:
            loader.download_post(post, target=post.owner_username)
        except instaloader.InstaloaderException as exc:
            logger.error("Failed to download %s: %s", url, exc)
        finally:
            storage.organize_instagram_account(account_dir)
            progress.refresh()


def _download_ytdlp_urls(
    urls: list[str], progress: storage.ReviewProgress, budget: TotalBudget | None = None
) -> None:
    """Download a batch of non-Instagram URLs via yt-dlp.

    Shares the configured URL destination, archive file (dedup), and per-item
    review/ refresh -- also used directly for a single ad-hoc URL passed to
    `yuno download <url>`.
    """
    if not urls:
        return
    # Apply total budget if provided.
    urls_to_download = urls
    if budget is not None:
        if budget.exhausted:
            logger.info("Total download limit reached; skipping URL batch.")
            return
        limit = budget.take(len(urls))
        if limit <= 0:
            logger.info("Total download limit reached; skipping URL batch.")
            return
        urls_to_download = urls[:limit]
        if len(urls_to_download) < len(urls):
            logger.info(
                "URL batch limited by --total-limit: downloading %d of %d URLs",
                len(urls_to_download),
                len(urls),
            )

    out_dir = config.DOWNLOADED_DIR / "other"
    archive = config.ARCHIVE_DIR / "other.txt"
    logger.info("Processing %d URL(s)...", len(urls_to_download))
    download(
        urls_to_download,
        str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "video.%(ext)s"),
        archive,
        metadata_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "metadata.%(ext)s"),
        caption_template=str(out_dir / "%(extractor)s" / "%(uploader)s" / "%(id)s" / "caption.%(ext)s"),
        on_item_done=functools.partial(storage.refresh_new_ytdlp_post, progress=progress),
    )

    storage.organize_ytdlp_tree(out_dir)


def download_urls(
    urls: list[str],
    progress: storage.ReviewProgress | None = None,
    budget: TotalBudget | None = None,
) -> None:
    """Route one or more ad-hoc URLs through the appropriate downloader."""
    if not urls:
        return
    progress = progress if progress is not None else storage.ReviewProgress()
    instagram_urls: list[str] = []
    other_urls: list[str] = []
    for url in urls:
        (instagram_urls if is_instagram_url(url) else other_urls).append(url)

    if instagram_urls:
        logger.info("Processing %d Instagram URL(s)...", len(instagram_urls))
        download_instagram_urls(instagram_urls, progress=progress)
    _download_ytdlp_urls(other_urls, progress, budget)


def harvest(
    progress: storage.ReviewProgress | None = None,
    budget: TotalBudget | None = None,
) -> None:
    all_urls = config.input_values("urls")
    if not all_urls:
        logger.info("No URLs configured, skipping")
        return
    download_urls(all_urls, progress=progress, budget=budget)
