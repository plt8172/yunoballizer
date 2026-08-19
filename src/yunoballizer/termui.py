"""Shared single-keypress terminal input, used by both select.py's photo
picker and larp.py's template browser.
"""
from __future__ import annotations

import sys

_ARROW_KEYS = {"A": "up", "B": "down", "C": "right", "D": "left"}
_WIN_ARROW_KEYS = {"H": "up", "P": "down", "M": "right", "K": "left"}


def read_key() -> str:
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
