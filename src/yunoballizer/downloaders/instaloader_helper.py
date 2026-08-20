"""Shared Instaloader setup and downloaded-post completeness checks."""
from __future__ import annotations

from pathlib import Path

import instaloader

from .. import storage


def new_loader(out_dir: Path) -> instaloader.Instaloader:
    return instaloader.Instaloader(
        dirname_pattern=str(out_dir / "{target}"),
        filename_pattern=f"{{shortcode}}/{storage.INSTAGRAM_FILENAME_PATTERN}",
        quiet=True,
        download_comments=False,
        download_video_thumbnails=False,
    )


def post_is_complete(post_dir: Path, expected_media_count: int) -> bool:
    if not post_dir.is_dir():
        return False
    downloaded_media_count = sum(
        1
        for path in post_dir.iterdir()
        if path.is_file() and path.suffix.lower() in storage.MEDIA_EXTS
    )
    return downloaded_media_count >= expected_media_count
