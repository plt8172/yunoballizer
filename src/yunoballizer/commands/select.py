"""Manual and LLM-assisted selection backed by one shared manifest.

Manual mode browses review/ one item at a time. Automatic mode judges new
posts from the manual selections and rejections in selected.json. Both record
their results there; export then materializes selected items into selected/.

Deliberately decoupled from the filesystem: review/ stays a disposable
symlink index (see storage.py), and the "what did I pick" state lives in
selected.json instead of being encoded via symlinks or deletions.

Saving the current item's caption as a larp template ('c') is a completely
separate action from picking favorites ('s'): it doesn't touch
selected.json or require the current item to be selected, and 's'
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

from .. import config, llm, termui
from ..storage import MEDIA_EXTS, VIDEO_EXTS, find_caption, review_link_name
from . import accounts as accounts_mod
from . import larp

logger = logging.getLogger(__name__)

MAX_EXAMPLES = 20
MAX_CAPTION_CHARS = 600


def _load_log() -> dict:
    if config.SELECTED_PATH.exists():
        return json.loads(config.SELECTED_PATH.read_text(encoding="utf-8"))
    return {}


def _save_log(log: dict) -> None:
    config.SELECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SELECTED_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_selected(entry: dict) -> bool:
    return entry.get("status") == "selected"


def selected_state() -> dict:
    """Return the shared manual/automatic selection state."""
    return _load_log()


def _selected_paths() -> set[Path]:
    """Return selected entries as canonical paths under the configured downloaded root."""
    downloaded_dir = config.DOWNLOADED_DIR.resolve()
    return {
        (downloaded_dir / key).resolve()
        for key, entry in _load_log().items()
        if _is_selected(entry)
    }


def _describe(path: Path) -> tuple[str, str, str, str]:
    """Pull (platform, account, post_id, filename) out of the downloaded/-relative
    path alone -- no metadata.json.xz parsing needed."""
    try:
        parts = path.resolve().relative_to(config.DOWNLOADED_DIR.resolve()).parts
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


def _account_action(path: Path, add: bool) -> str:
    """Add/remove the current item's account ID in inputs.json."""
    platform, account, _post_id, _filename = _describe(path)
    if platform not in accounts_mod.PLATFORMS or not account or account == "unknown":
        return "No monitored account for this item."
    if add:
        changed = accounts_mod.add(platform, account)
        return f"{'Added' if changed else 'Already present:'} @{account} ({platform})"
    changed = accounts_mod.remove(platform, account)
    return f"{'Removed' if changed else 'Not found:'} @{account} ({platform})"


def _render_item(
    path: Path,
    index: int,
    total: int,
    marked: set[Path],
    status: str = "",
    rejected: set[Path] | None = None,
) -> None:
    print("\x1b[2J\x1b[H", end="")
    resolved = path.resolve()
    platform, account, post_id, filename = _describe(path)
    size = _format_size(resolved.stat().st_size)
    if resolved in marked:
        decision = " [SELECTED]"
    elif rejected is not None and resolved in rejected:
        decision = " [REJECTED]"
    else:
        decision = ""
    header = (
        f"[{index + 1}/{total}] {platform} / {account} / {post_id} / "
        f"{filename} ({size}){decision}"
    )
    footer = (
        "<-/-> move   s select   d reject   c save caption as larp template   "
        "ctrl+s add account   ctrl+d remove account   o open natively   Enter/q finish"
    )

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
    if status:
        print(status)
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


def pick(
    source_dir: Path | None = None,
    rejected: set[Path] | None = None,
) -> list[Path]:
    """Browse source_dir and return selections while collecting explicit rejections.

    Marked paths are resolved (symlinks in review/ followed) so callers get
    the canonical downloaded/ path rather than the disposable review/ link.
    If rejected is provided, pressing 'd' adds the resolved path to that set.
    """
    source_dir = source_dir if source_dir is not None else config.REVIEW_DIR
    files = sorted(p for p in source_dir.iterdir() if p.is_file()) if source_dir.exists() else []
    if not files:
        return []

    index = 0
    available = {path.resolve() for path in files}
    marked = _selected_paths() & available
    rejected = rejected if rejected is not None else set()
    _render_item(files[index], index, len(files), marked, rejected=rejected)
    while True:
        key = termui.read_key()
        status = ""
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
            marked.add(resolved)
            rejected.discard(resolved)
        elif key == "d":
            resolved = files[index].resolve()
            marked.discard(resolved)
            rejected.add(resolved)
        elif key == "\x13":  # ctrl+s
            status = _account_action(files[index], add=True)
        elif key == "\x04":  # ctrl+d
            status = _account_action(files[index], add=False)
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
        _render_item(files[index], index, len(files), marked, status, rejected=rejected)

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


def record_selection(
    paths: list[Path],
    candidates: list[Path] | None = None,
    rejected: set[Path] | None = None,
) -> int:
    """Update selected paths and return the number of selection-state changes.

    When candidates is supplied, newly selected items become manual selections
    and previously selected items that were deselected become manual
    rejections. Untouched undecided items remain undecided so automatic
    selection may judge them. Without candidates, the supplied paths are
    selected additively.
    """
    log = _load_log()
    downloaded_dir = config.DOWNLOADED_DIR.resolve()
    updated = dict(log)
    chosen = {path.resolve() for path in paths}
    explicitly_rejected = {path.resolve() for path in rejected or set()}

    if candidates is not None:
        for path in candidates:
            try:
                key = str(path.resolve().relative_to(downloaded_dir))
            except ValueError:
                continue
            previous = log.get(key, {})
            if path.resolve() in chosen:
                if previous.get("status") == "selected":
                    continue
                status = "selected"
            elif path.resolve() in explicitly_rejected:
                status = "rejected"
            elif previous.get("status") == "selected":
                status = "rejected"
            else:
                # Merely leaving an unseen/unselected item unmarked is not an
                # explicit rejection. Keep it undecided so automatic selection
                # may judge it.
                continue
            if previous.get("status") == status and previous.get("source") == "manual":
                continue
            updated[key] = {
                "status": status,
                "source": "manual",
                "decided_at": time.time(),
            }

    for path in paths:
        try:
            key = str(path.resolve().relative_to(downloaded_dir))
        except ValueError:
            logger.warning("Skipping %s: not under downloaded/", path)
            continue
        if candidates is not None:
            continue
        previous = log.get(key, {})
        if previous.get("status") == "selected" and previous.get("source") == "manual":
            continue
        updated[key] = {
            "status": "selected",
            "source": "manual",
            "decided_at": time.time(),
        }

    changes = sum(1 for key in set(log) | set(updated) if log.get(key) != updated.get(key))
    if changes:
        _save_log(updated)
    return changes


def record_automatic_selections(selections: dict[Path, bool]) -> int:
    """Persist automatic selections without overriding any manual selection."""
    log = _load_log()
    updated = dict(log)
    downloaded_dir = config.DOWNLOADED_DIR.resolve()

    for path, keep in selections.items():
        try:
            key = str(path.resolve().relative_to(downloaded_dir))
        except ValueError:
            continue
        if log.get(key, {}).get("source") == "manual":
            continue
        updated[key] = {
            "status": "selected" if keep else "rejected",
            "source": "auto",
            "decided_at": time.time(),
        }

    changes = sum(1 for key in set(log) | set(updated) if log.get(key) != updated.get(key))
    if changes:
        _save_log(updated)
    return changes


def _taste_context(log: dict) -> str:
    examples: dict[str, list[str]] = {"selected": [], "rejected": []}
    seen_posts: set[Path] = set()

    ordered_entries = sorted(
        log.items(), key=lambda item: item[1].get("decided_at", 0), reverse=True
    )
    for key, entry in ordered_entries:
        status = entry.get("status")
        if entry.get("source") != "manual" or status not in examples:
            continue
        media_path = config.DOWNLOADED_DIR / key
        if media_path.parent in seen_posts:
            continue
        seen_posts.add(media_path.parent)
        caption = find_caption(media_path).strip()
        if caption:
            examples[status].append(caption[:MAX_CAPTION_CHARS])
        if sum(len(items) for items in examples.values()) >= MAX_EXAMPLES:
            break

    parts = []
    if examples["selected"]:
        parts.append(
            "Posts the user manually selected:\n"
            + "\n\n".join(f"- {caption}" for caption in examples["selected"])
        )
    if examples["rejected"]:
        parts.append(
            "Posts the user manually rejected:\n"
            + "\n\n".join(f"- {caption}" for caption in examples["rejected"])
        )
    if not parts:
        raise SystemExit(
            "Automatic selection needs a taste signal. Manually select or reject at least "
            "one captioned item with `yuno select`."
        )
    return "\n\n".join(parts)


def _ask_llm(candidate: Path, taste_context: str, *, api_key: str) -> bool:
    platform, account, _post_id, _filename = _describe(candidate)
    caption = find_caption(candidate).strip()[:MAX_CAPTION_CHARS]
    prompt = f"""Decide whether a new social-media post matches this user's demonstrated taste.

Taste evidence:
{taste_context}

Candidate:
- platform: {platform}
- account: @{account}
- caption: {caption or "(none)"}

Answer with exactly one word: yes or no."""
    answer = llm.call(prompt, api_key=api_key, max_tokens=5, temperature=0)
    return answer.strip().lower() == "yes"


def _unreviewed_posts(log: dict) -> list[list[Path]]:
    reviewed = set(log)
    posts: dict[Path, list[Path]] = {}
    if not config.DOWNLOADED_DIR.exists():
        return []
    for path in config.DOWNLOADED_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTS:
            continue
        posts.setdefault(path.parent, []).append(path)
    return [
        sorted(paths)
        for paths in posts.values()
        if not any(
            str(path.resolve().relative_to(config.DOWNLOADED_DIR.resolve())) in reviewed
            for path in paths
        )
    ]


def run_auto(*, limit: int = 20) -> None:
    api_key = llm.resolve_api_key()
    if not api_key:
        raise SystemExit("No LLM profile configured. Run `yuno brain config` first.")

    log = selected_state()
    context = _taste_context(log)
    selections: dict[Path, bool] = {}
    checked = kept = 0

    for media_paths in _unreviewed_posts(log)[:limit]:
        try:
            keep = _ask_llm(media_paths[0], context, api_key=api_key)
        except llm.LlmError as exc:
            logger.error("LLM judgment failed for %s: %s", media_paths[0].parent, exc)
            continue
        checked += 1
        kept += int(keep)
        selections.update({path: keep for path in media_paths})

    changed = record_automatic_selections(selections)
    logger.info(
        "Automatically reviewed: %d posts, selected: %d, selection state changes: %d",
        checked,
        kept,
        changed,
    )


def export() -> int:
    """Materialize every selected media file into selected/ as a real file
    (hardlink where possible, copy otherwise). Idempotent."""
    log = _load_log()
    config.SELECTED_DIR.mkdir(parents=True, exist_ok=True)

    exported = 0
    for key, entry in log.items():
        if not _is_selected(entry):
            continue
        source = config.DOWNLOADED_DIR / key
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
    rejected: set[Path] = set()
    marked = pick(rejected=rejected)
    candidates = (
        [path for path in config.REVIEW_DIR.iterdir() if path.is_file()]
        if config.REVIEW_DIR.exists()
        else []
    )
    changes = record_selection(marked, candidates=candidates, rejected=rejected)
    logger.info("Selected: %d, selection state changes: %d", len(marked), changes)


def run_export() -> None:
    exported = export()
    logger.info("Exported to %s: %d", config.SELECTED_DIR, exported)
