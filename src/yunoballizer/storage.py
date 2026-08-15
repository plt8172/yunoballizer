"""Post-bundle filesystem layout: canonical naming and the flat review index.

Every downloaded post lives as a single self-contained directory under
sources/<platform>/<account>/<post-id>/ holding its media, caption, and
compressed metadata together (image_01.jpg, video.mp4, caption.txt,
metadata.json.xz). review/ is a disposable flat index of symlinks into that
tree; deleting it and re-running `download` regenerates it from sources/.
"""
from __future__ import annotations

import hashlib
import logging
import lzma
import os
import re
import shutil
from pathlib import Path

from . import config

logger = logging.getLogger("yunoballizer.storage")

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mp4", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

_INDEXED_NAME_RE = re.compile(r"^(?:_(\d+))?(\.[A-Za-z0-9.]+)$")
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")

INSTAGRAM_FILENAME_PATTERN = "post"


# --------------------------------------------------------------------------
# Canonical per-post naming.
# --------------------------------------------------------------------------

def _move_entry(source: Path, destination: Path) -> None:
    if source == destination:
        return
    if destination.exists():
        logger.warning("Skipped %s: %s already exists", source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def _compress_json(source: Path, destination: Path) -> None:
    if destination.exists():
        logger.warning("Skipped %s: %s already exists", source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(lzma.compress(source.read_bytes()))
    source.unlink()


def _assign_canonical_names(
    entries: list[tuple[Path, int | None, str]],
) -> dict[Path, str]:
    """Map each (path, carousel index, suffix) entry to its canonical filename."""
    images: list[tuple[int, Path, str]] = []
    videos: list[tuple[int, Path, str]] = []
    caption_path: Path | None = None
    metadata_path: Path | None = None

    for path, idx, suffix in entries:
        ext = suffix.lower()
        if ext == ".txt":
            if caption_path is not None:
                logger.warning("Multiple captions found for one post; keeping %s over %s", path, caption_path)
            caption_path = path
        elif ext in (".json.xz", ".json"):
            if metadata_path is not None:
                logger.warning("Multiple metadata files found for one post; keeping %s over %s", path, metadata_path)
            metadata_path = path
        elif ext in IMAGE_EXTS:
            images.append((idx if idx is not None else 0, path, ext))
        elif ext in VIDEO_EXTS:
            videos.append((idx if idx is not None else 0, path, ext))

    names: dict[Path, str] = {}
    if caption_path is not None:
        names[caption_path] = "caption.txt"
    if metadata_path is not None:
        names[metadata_path] = "metadata.json.xz"

    for label, items in (("image", images), ("video", videos)):
        items.sort(key=lambda t: t[0])
        if len(items) == 1:
            _, path, ext = items[0]
            names[path] = f"{label}{ext}"
        else:
            for position, (_, path, ext) in enumerate(items, start=1):
                names[path] = f"{label}_{position:02d}{ext}"
    return names


def _place_canonical_entries(entries: list[tuple[Path, int | None, str]], post_dir: Path) -> None:
    for source, canonical_name in _assign_canonical_names(entries).items():
        destination = post_dir / canonical_name
        if canonical_name == "metadata.json.xz" and source.suffix == ".json":
            _compress_json(source, destination)
        else:
            _move_entry(source, destination)


# --------------------------------------------------------------------------
# Fresh-download organizing: Instagram uses a static "post"/"post_<n>"
# filename pattern so its output is renamed in place after each account;
# yt-dlp is pointed at canonical names directly except for the info.json
# and description sidecars, which yt-dlp forces its own extension onto.
# --------------------------------------------------------------------------

def _parse_indexed_name(name: str, prefix: str) -> tuple[int | None, str] | None:
    if not name.startswith(prefix):
        return None
    match = _INDEXED_NAME_RE.match(name[len(prefix):])
    if not match:
        return None
    idx = int(match.group(1)) if match.group(1) else None
    return idx, match.group(2)


def organize_instagram_account(account_dir: Path) -> None:
    """Rename a freshly downloaded account's post directories to canonical names.

    Also drops anything Instaloader wrote directly in the account dir instead
    of a post's subdirectory -- e.g. its own profile-level metadata JSON
    (<account>_<userid>.json.xz) or resume-iterator file. sources/ is meant
    to hold nothing but post bundles, and we don't use either of those.
    """
    if not account_dir.exists():
        return
    for entry in account_dir.iterdir():
        if entry.is_file():
            entry.unlink()
            continue
        if not entry.is_dir():
            continue
        post_dir = entry
        entries = []
        for path in post_dir.iterdir():
            if not path.is_file():
                continue
            parsed = _parse_indexed_name(path.name, INSTAGRAM_FILENAME_PATTERN)
            if parsed is None:
                continue
            idx, suffix = parsed
            entries.append((path, idx, suffix))
        if entries:
            _place_canonical_entries(entries, post_dir)


def organize_ytdlp_post_dir(post_dir: Path) -> None:
    info_json = post_dir / "metadata.info.json"
    if info_json.exists():
        destination = post_dir / "metadata.json.xz"
        if destination.exists():
            info_json.unlink()
        else:
            destination.write_bytes(lzma.compress(info_json.read_bytes()))
            info_json.unlink()

    description = post_dir / "caption.description"
    if description.exists():
        destination = post_dir / "caption.txt"
        if destination.exists():
            description.unlink()
        else:
            shutil.move(str(description), str(destination))


def organize_ytdlp_tree(root: Path) -> None:
    """Organize every post directory under a freshly-downloaded yt-dlp subtree."""
    if not root.exists():
        return
    for directory in root.rglob("*"):
        if directory.is_dir():
            organize_ytdlp_post_dir(directory)


def find_caption(media_path: Path) -> str:
    """A post's caption lives beside its media, in the same bundle directory."""
    post_dir = media_path.parent
    caption_path = post_dir / "caption.txt"
    if caption_path.exists():
        return caption_path.read_text(encoding="utf-8", errors="ignore")

    metadata_path = post_dir / "metadata.json.xz"
    if metadata_path.exists():
        try:
            with lzma.open(metadata_path) as f:
                data = json.loads(f.read())
        except Exception:
            return ""
        return data.get("description") or data.get("title") or ""
    return ""


# --------------------------------------------------------------------------
# review/: a disposable flat symlink index over sources/.
# --------------------------------------------------------------------------

def review_link_name(sources_relpath: Path) -> str:
    """Build a readable, collision-safe review/ link name for a sources/-relative media path.

    The name embeds platform/account/post-id/media for readability, plus a
    short stable hash of the full relative path so it never needs to be
    parsed back to recover that information.
    """
    parts = sources_relpath.parts
    platform = parts[0]
    post_id = parts[-2]
    account = "-".join(parts[1:-2]) or "unknown"
    media_name = parts[-1]
    stem, ext = os.path.splitext(media_name)
    digest = hashlib.sha256(sources_relpath.as_posix().encode("utf-8")).hexdigest()[:8]

    def clean(value: str) -> str:
        return _UNSAFE_CHARS_RE.sub("_", value).strip("_") or "x"

    return f"{clean(platform)}-{clean(account)}-{clean(post_id)}-{clean(stem)}-{digest}{ext.lower()}"


def _prune_dangling_review_links() -> None:
    if not config.REVIEW_DIR.exists():
        return
    for entry in config.REVIEW_DIR.iterdir():
        if entry.is_symlink() and not entry.exists():
            entry.unlink()


def refresh_review() -> int:
    """Add any un-indexed sources/ media to the flat review/ symlink view."""
    config.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    _prune_dangling_review_links()

    added = 0
    if not config.SOURCES_DIR.exists():
        return added

    for media_path in config.SOURCES_DIR.rglob("*"):
        if not media_path.is_file() or media_path.suffix.lower() not in MEDIA_EXTS:
            continue
        if "profile_pic" in media_path.stem.lower():
            continue
        relative = media_path.relative_to(config.SOURCES_DIR)
        if len(relative.parts) < 3:
            continue
        name = review_link_name(relative)
        link_path = config.REVIEW_DIR / name
        if link_path.exists() or link_path.is_symlink():
            continue
        target = os.path.relpath(media_path, start=link_path.parent)
        link_path.symlink_to(target)
        added += 1
    return added
