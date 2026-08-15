"""Manual photo selection: mark favorites in review/ with an external image
viewer, record the choice in a manifest, then materialize it into selected/.

Deliberately decoupled from the filesystem: review/ stays a disposable
symlink index (see storage.py), and the "what did I pick" state lives in
selection_log.json instead of being encoded via symlinks or deletions.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .storage import review_link_name

logger = logging.getLogger("yunoballizer.select")

DEFAULT_VIEWER = ["nsxiv", "-o", "-t"]


def _load_log() -> dict:
    if config.SELECTION_LOG_PATH.exists():
        return json.loads(config.SELECTION_LOG_PATH.read_text(encoding="utf-8"))
    return {}


def _save_log(log: dict) -> None:
    config.SELECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SELECTION_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(source_dir: Path | None = None, viewer: list[str] | None = None) -> list[Path]:
    """Launch an image viewer's mark mode over source_dir and return the marked files.

    Marked paths are resolved (symlinks in review/ followed) so callers get
    the canonical sources/ path rather than the disposable review/ link.
    """
    cmd = [*(viewer or DEFAULT_VIEWER), str(source_dir if source_dir is not None else config.REVIEW_DIR)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SystemExit(
            f"Image viewer '{cmd[0]}' not found. Install nsxiv, or pass a different "
            "command with --viewer."
        )
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"'{cmd[0]}' exited with an error: {e.stderr.strip()}")

    return [Path(line).resolve() for line in result.stdout.splitlines() if line.strip()]


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


def run_select(viewer: list[str] | None = None) -> None:
    marked = pick(viewer=viewer)
    added = record_selection(marked)
    logger.info("Marked: %d, newly added to selection manifest: %d", len(marked), added)


def run_export() -> None:
    exported = export()
    logger.info("Exported to %s: %d", config.SELECTED_DIR, exported)
