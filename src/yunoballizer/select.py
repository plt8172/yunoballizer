"""Manual photo selection: browse review/ one item at a time, record picks in
a manifest, then materialize the manifest into selected/.

Deliberately decoupled from the filesystem: review/ stays a disposable
symlink index (see storage.py), and the "what did I pick" state lives in
selection_log.json instead of being encoded via symlinks or deletions.

Saving the current item's caption as a larp template ('c') is a completely
separate action from picking favorites ('s'): it doesn't touch
selection_log.json or require the current item to be selected, and 's'
never touches larp's template files. See larp.py for where it lands.

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

from . import config, larp
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


def _selected_paths() -> set[Path]:
    """Return manifest entries as canonical paths under the configured sources root."""
    sources_dir = config.SOURCES_DIR.resolve()
    return {(sources_dir / key).resolve() for key in _load_log()}


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
        parts = path.resolve().relative_to(config.SOURCES_DIR.resolve()).parts
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
    header = f"[{index + 1}/{total}] {platform} / {account} / {post_id} / {filename} ({size}){star}"
    footer = "<-/-> move   s select/deselect   c save caption as larp template   o open natively   Enter/q finish"

    # Truncate to a single line (not wrapped) so its screen-row cost is
    # predictable -- a caption that wraps across several rows would throw
    # off the line budget below.
    columns = shutil.get_terminal_size().columns
    caption = find_caption(resolved).strip().replace("\n", " ")
    caption_line = caption[: max(columns - 1, 10)] if caption else ""

    # This budget makes the image a sensible size in the common case, but
    # it's not what keeps the header on screen -- viu's requested -h isn't
    # guaranteed to match what actually gets drawn (graphics protocols need
    # an accurate pixel-per-cell size from the terminal, which isn't always
    # reported correctly). So the image is printed *first*, before anything
    # else: if it renders taller than expected and forces a scroll, only the
    # top of the image scrolls out of view. Whatever's printed last (header,
    # caption, footer) always stays on screen regardless of how tall the
    # image actually turns out to be.
    reserved = 4 + (1 if caption_line else 0)
    height = max(shutil.get_terminal_size().lines - reserved, 5)

    render_preview(path, height=height)
    print()
    print(header)
    if caption_line:
        print(caption_line)
    print()
    print(footer)
    sys.stdout.flush()


def _style_completer(styles: list[str]):
    """Build a readline completer function that offers existing style names."""
    def complete(text: str, state: int) -> str | None:
        matches = [s for s in styles if s.startswith(text)]
        return matches[state] if state < len(matches) else None
    return complete


def _prompt_larp_style() -> str | None:
    """Prompt for which style to file the current item's caption under; None if cancelled.

    Tab-completes over existing styles when readline is available (not on
    Windows without pyreadline), but typing a new name still works to create
    a new style.
    """
    styles = larp.list_styles()
    if styles:
        print("Styles: " + ", ".join(styles))

    try:
        import readline
    except ImportError:
        readline = None

    if readline is not None:
        old_completer = readline.get_completer()
        old_delims = readline.get_completer_delims()
        readline.set_completer(_style_completer(styles))
        readline.set_completer_delims("")
        readline.parse_and_bind("tab: complete")

    try:
        style = input("save as style (Tab completes)> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    finally:
        if readline is not None:
            readline.set_completer(old_completer)
            readline.set_completer_delims(old_delims)
    return style or None


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
    available = {path.resolve() for path in files}
    marked = _selected_paths() & available
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
        elif key == "c":
            caption = find_caption(files[index].resolve()).strip()
            print()
            if not caption:
                print("No caption on this item -- nothing to save.")
                input("Press Enter to continue...")
            else:
                style = _prompt_larp_style()
                if style is not None:
                    try:
                        larp.add_template(style, caption)
                    except ValueError as exc:
                        print(f"Could not save: {exc}")
                        input("Press Enter to continue...")
        else:
            continue
        _render_item(files[index], index, len(files), marked)

    return list(marked)


def render_preview(path: Path, height: int | None = None) -> None:
    """Print a preview of the current item to stdout, scaled to fit height
    rows so it never gets cropped.

    Only height is constrained (not both width and height -- viu stretches
    and distorts the aspect ratio when both are given). Sizing by height
    alone works well here because this project's content is overwhelmingly
    portrait/square (Instagram posts, Shorts, Reels): scaling those to fit
    the available rows keeps the width comfortably inside the terminal too.

    height defaults to the terminal's own height (minus a small margin) for
    standalone use; _render_item() passes an exact budget that also accounts
    for the header/caption/footer lines it prints around the image.

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
        fd, tmp_name = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        tmp_frame = Path(tmp_name)
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

    if height is None:
        height = max(shutil.get_terminal_size().lines - 3, 5)
    sys.stdout.flush()
    try:
        subprocess.run(["viu", "-h", str(height), str(target)])
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


def record_selection(paths: list[Path], candidates: list[Path] | None = None) -> int:
    """Update selected paths and return the number of manifest changes.

    When candidates is supplied, entries in that browsed set are synchronized
    so deselections are recorded. Entries outside the set remain untouched.
    Without candidates this retains the original additive behavior.
    """
    log = _load_log()
    sources_dir = config.SOURCES_DIR.resolve()
    selected = dict(log)

    if candidates is not None:
        for path in candidates:
            try:
                key = str(path.resolve().relative_to(sources_dir))
            except ValueError:
                continue
            selected.pop(key, None)

    for path in paths:
        try:
            key = str(path.resolve().relative_to(sources_dir))
        except ValueError:
            logger.warning("Skipping %s: not under sources/", path)
            continue
        selected[key] = log.get(key, {"selected_at": time.time()})

    changes = len(set(log) ^ set(selected))
    if changes:
        _save_log(selected)
    return changes


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
    candidates = (
        [path for path in config.REVIEW_DIR.iterdir() if path.is_file()]
        if config.REVIEW_DIR.exists()
        else []
    )
    changes = record_selection(marked, candidates=candidates)
    logger.info("Selected: %d, selection manifest changes: %d", len(marked), changes)


def run_export() -> None:
    exported = export()
    logger.info("Exported to %s: %d", config.SELECTED_DIR, exported)
