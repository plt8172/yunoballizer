"""Shared helper for calling yt-dlp as a library.

Importing yt_dlp directly instead of shelling out to its CLI lets us handle
download success/failure at the Python level instead of parsing log text.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yt_dlp


def download(
    urls: str | Iterable[str],
    out_template: str,
    archive: Path,
    extra_opts: dict | None = None,
) -> None:
    if isinstance(urls, str):
        urls = [urls]

    opts = {
        "download_archive": str(archive),
        "writeinfojson": True,
        "outtmpl": out_template,
        "ignoreerrors": True,
        "sleep_interval_requests": 2,
        "quiet": True,
        "no_warnings": True,
    }
    if extra_opts:
        opts.update(extra_opts)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(list(urls))
