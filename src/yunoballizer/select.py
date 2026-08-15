"""Manual photo selection: mark favorites in review/ with fzf, record the
choice in a manifest, then materialize it into selected/.

Deliberately decoupled from the filesystem: review/ stays a disposable
symlink index (see storage.py), and the "what did I pick" state lives in
selection_log.json instead of being encoded via symlinks or deletions.

fzf's preview pane and the 'o' keybind shell out to this project's own
`yuno _preview`/`yuno _open` subcommands (see cli.py) rather than an inline
shell script, so nothing here depends on which shell fzf happens to invoke
on a given platform (POSIX sh vs. Windows cmd.exe).
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
from .storage import VIDEO_EXTS, review_link_name

logger = logging.getLogger("yunoballizer.select")

FZF_CANCELLED = 130


def _load_log() -> dict:
    if config.SELECTION_LOG_PATH.exists():
        return json.loads(config.SELECTION_LOG_PATH.read_text(encoding="utf-8"))
    return {}


def _save_log(log: dict) -> None:
    config.SELECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SELECTION_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(source_dir: Path | None = None) -> list[Path]:
    """Browse source_dir in fzf (Tab to mark, Enter to confirm) and return the marked files.

    Marked paths are resolved (symlinks in review/ followed) so callers get
    the canonical sources/ path rather than the disposable review/ link.
    """
    source_dir = source_dir if source_dir is not None else config.REVIEW_DIR
    files = sorted(p for p in source_dir.iterdir() if p.is_file()) if source_dir.exists() else []
    if not files:
        return []

    cmd = [
        "fzf", "--multi",
        "--preview", "yuno _preview {}",
        "--preview-window", "right,60%",
        "--bind", "o:execute-silent(yuno _open {})",
    ]
    try:
        result = subprocess.run(
            cmd, input="\n".join(str(p) for p in files), capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise SystemExit("fzf not found. Install fzf to use `yuno select`.")

    if result.returncode == FZF_CANCELLED:
        return []
    if result.returncode != 0:
        raise SystemExit(f"fzf exited with an error: {result.stderr.strip()}")

    return [Path(line).resolve() for line in result.stdout.splitlines() if line.strip()]


def render_preview(path: Path) -> None:
    """Print a preview of path to stdout for fzf's preview pane.

    Videos get a single representative frame (via ffmpeg) shown as an image;
    anything ffmpeg/viu can't handle degrades to a placeholder line instead
    of raising, since this runs once per highlighted item in the picker.
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

    width = os.environ.get("FZF_PREVIEW_COLUMNS", "80")
    try:
        subprocess.run(["viu", "-w", width, str(target)])
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
