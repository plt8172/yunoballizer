"""Shared helper for calling yt-dlp as a library.

Importing yt_dlp directly instead of shelling out to its CLI lets us handle
download success/failure at the Python level instead of parsing log text.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable

import yt_dlp


def _make_progress_hook(on_item_done: Callable[[Path], None]) -> Callable[[dict], None]:
    def hook(d: dict) -> None:
        if d.get("status") != "finished":
            return
        filename = d.get("filename") or d.get("info_dict", {}).get("filepath")
        if not filename:
            return
        path = Path(filename)
        # Skip temporary files from format merging (e.g., "video.f18.mp4", "audio.f140.m4a").
        # These are intermediate files that get deleted/renamed by organize_ytdlp_tree.
        if re.search(r"\.f\d+$", path.stem):
            return
        on_item_done(path.parent)

    return hook


def download(
    urls: str | Iterable[str],
    out_template: str,
    archive: Path,
    extra_opts: dict | None = None,
    metadata_template: str | None = None,
    caption_template: str | None = None,
    on_item_done: Callable[[Path], None] | None = None,
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
    if on_item_done is not None:
        # Fires once per finished media file (not once per post overall for a
        # multi-format merge), but with the single-format downloads used here
        # that's the same thing -- lets review/ pick up each post as soon as
        # it lands instead of only after the whole account/playlist finishes.
        opts["progress_hooks"] = [_make_progress_hook(on_item_done)]
    if extra_opts:
        opts.update(extra_opts)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(list(urls))
