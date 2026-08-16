"""Manual photo selection: browse review/ one item at a time, record picks in
a manifest, then materialize the manifest into selected/.

Deliberately decoupled from the filesystem: review/ stays a disposable
symlink index (see storage.py), and the "what did I pick" state lives in
selection_log.json instead of being encoded via symlinks or deletions.

The picker shows one item at a time (account / image / caption) rather than
a live list-plus-preview split. That's not just simplicity for its own sake:
splitting the screen between a navigable list and a concurrently-rendered
image (as fzf's --preview does) means two processes fight over the same
terminal at once -- the list reads keystrokes from stdin while the image
tool queries the terminal for cursor position over that same stdin, and the
terminal's pixel-per-cell report is often unreliable inside a piped preview
subprocess. Both cause real, frequent corruption in practice. Rendering
one item at a time means only one process ever touches the terminal at a
time, and it always finishes before the next keypress is read.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config
from .storage import VIDEO_EXTS, find_caption, review_link_name

logger = logging.getLogger("yunoballizer.select")

_ARROW_KEYS = {"A": "up", "B": "down", "C": "right", "D": "left"}
_WIN_ARROW_KEYS = {"H": "up", "P": "down", "M": "right", "K": "left"}


def _load_log() -> dict:
    if config.SELECTION_LOG_PATH.exists():
        return json.loads(config.SELECTION_LOG_PATH.read_text(encoding="utf-8"))
    return {}


def _save_log(log: dict) -> None:
    config.SELECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SELECTION_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_key() -> str:
    """Block for a single raw keypress, normalizing arrow keys to up/down/left/right."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return _WIN_ARROW_KEYS.get(ch2.decode(errors="ignore"), "")
        return ch.decode(errors="ignore")

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            if sys.stdin.read(1) == "[":
                return _ARROW_KEYS.get(sys.stdin.read(1), "")
            return "esc"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _describe(path: Path) -> tuple[str, str, str, str]:
    """Pull (platform, account, post_id, filename) out of the sources/-relative
    path alone -- no metadata.json.xz parsing needed."""
    try:
        parts = path.resolve().relative_to(config.SOURCES_DIR).parts
    except ValueError:
        parts = ()
    if len(parts) < 3:
        return "", "", "", path.name
    platform = parts[0]
    post_id = parts[-2]
    account = "/".join(parts[1:-2]) or "unknown"
    filename = parts[-1]
    return platform, account, post_id, filename


def _format_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def _render_item(path: Path, index: int, total: int, marked: set[Path]) -> None:
    print("\x1b[2J\x1b[H", end="")
    resolved = path.resolve()
    platform, account, post_id, filename = _describe(path)
    size = _format_size(resolved.stat().st_size)
    star = " [SELECTED]" if resolved in marked else ""
    print(f"[{index + 1}/{total}] {platform} / {account} / {post_id} / {filename} ({size}){star}")
    print()
    render_preview(path)
    print()
    caption = find_caption(resolved).strip()
    if caption:
        print(caption[:300])
        print()
    print("<-/-> move   s select/deselect   o open natively   Enter/q finish")


def pick(source_dir: Path | None = None) -> list[Path]:
    """Browse source_dir one item at a time and return whatever got marked with 's'.

    Marked paths are resolved (symlinks in review/ followed) so callers get
    the canonical sources/ path rather than the disposable review/ link.
    """
    source_dir = source_dir if source_dir is not None else config.REVIEW_DIR
    files = sorted(p for p in source_dir.iterdir() if p.is_file()) if source_dir.exists() else []
    if not files:
        return []

    index = 0
    marked: set[Path] = set()
    _render_item(files[index], index, len(files), marked)
    while True:
        key = _read_key()
        if key in ("\r", "\n", "q", "\x03"):
            break
        elif key in ("left", "up"):
            new_index = max(index - 1, 0)
            if new_index == index:
                continue
            index = new_index
        elif key in ("right", "down"):
            new_index = min(index + 1, len(files) - 1)
            if new_index == index:
                continue
            index = new_index
        elif key == "s":
            resolved = files[index].resolve()
            if resolved in marked:
                marked.remove(resolved)
            else:
                marked.add(resolved)
        elif key == "o":
            open_native(files[index])
        else:
            continue
        _render_item(files[index], index, len(files), marked)

    return list(marked)


def render_preview(path: Path) -> None:
    """Print a preview of the current item to stdout, scaled to fit the
    terminal's height so it never gets cropped.

    Only height is constrained (not both width and height -- viu stretches
    and distorts the aspect ratio when both are given). Sizing by height
    alone works well here because this project's content is overwhelmingly
    portrait/square (Instagram posts, Shorts, Reels): scaling those to fit
    the available rows keeps the width comfortably inside the terminal too.

    Videos get a single representative frame (via ffmpeg) shown as an image;
    anything ffmpeg/viu can't handle degrades to a placeholder line instead
    of raising, since this runs once per item shown in the picker.
    """
    if not path.exists():
        print(f"[missing: {path.name}]")
        return

    target = path
    tmp_frame: Path | None = None
    if path.suffix.lower() in VIDEO_EXTS:
        tmp_frame = Path(tempfile.mkstemp(suffix=".jpg")[1])
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                 "-frames:v", "1", "-q:v", "3", str(tmp_frame)],
                check=True, capture_output=True,
            )
            target = tmp_frame
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"[video: {path.name} -- install ffmpeg to preview a frame]")
            tmp_frame.unlink(missing_ok=True)
            return

    height = str(max(shutil.get_terminal_size().lines - 3, 5))
    try:
        subprocess.run(["viu", "-h", height, str(target)])
    except FileNotFoundError:
        print(f"[install viu to preview: {path.name}]")
    finally:
        if tmp_frame is not None:
            tmp_frame.unlink(missing_ok=True)


def open_native(path: Path) -> None:
    """Open path in the OS's default viewer/player, for a closer look or editing."""
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)])


def record_selection(paths: list[Path]) -> int:
    """Add newly marked media to the selection manifest. Returns count actually added."""
    log = _load_log()
    added = 0
    for path in paths:
        try:
            key = str(path.relative_to(config.SOURCES_DIR))
        except ValueError:
            logger.warning("Skipping %s: not under sources/", path)
            continue
        if key in log:
            continue
        log[key] = {"selected_at": time.time()}
        added += 1
    if added:
        _save_log(log)
    return added


def export() -> int:
    """Materialize every selected media file into selected/ as a real file
    (hardlink where possible, copy otherwise). Idempotent."""
    log = _load_log()
    config.SELECTED_DIR.mkdir(parents=True, exist_ok=True)

    exported = 0
    for key in log:
        source = config.SOURCES_DIR / key
        if not source.exists():
            logger.warning("Selected file missing, skipping: %s", source)
            continue
        destination = config.SELECTED_DIR / review_link_name(Path(key))
        if destination.exists():
            continue
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        exported += 1
    return exported


def run_select() -> None:
    marked = pick()
    added = record_selection(marked)
    logger.info("Marked: %d, newly added to selection manifest: %d", len(marked), added)


def run_export() -> None:
    exported = export()
    logger.info("Exported to %s: %d", config.SELECTED_DIR, exported)
