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
    metadata_template: str | None = None,
    caption_template: str | None = None,
) -> None:
    if isinstance(urls, str):
        urls = [urls]

    output_templates: str | dict[str, str] = out_template
    if metadata_template or caption_template:
        output_templates = {"default": out_template}
        if metadata_template:
            output_templates["infojson"] = metadata_template
        if caption_template:
            output_templates["description"] = caption_template

    opts = {
        "download_archive": str(archive),
        "writeinfojson": True,
        "allow_playlist_files": False,
        "outtmpl": output_templates,
        "ignoreerrors": True,
        "sleep_interval_requests": 2,
        "quiet": True,
        "no_warnings": True,
    }
    if caption_template:
        opts["writedescription"] = True
    if extra_opts:
        opts.update(extra_opts)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(list(urls))
