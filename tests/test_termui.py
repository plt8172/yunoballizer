from __future__ import annotations

import unittest
from unittest.mock import patch

from yunoballizer import termui


class ReadKeyTests(unittest.TestCase):
    def _read_key_with_stdin(self, chars: list[str]) -> str:
        with (
            patch("termios.tcgetattr", return_value=object()),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
            patch.object(termui.sys.stdin, "read", side_effect=chars),
            patch.object(termui.sys, "platform", "linux"),
        ):
            return termui.read_key()

    def test_regular_key_returned_as_is(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["a"]), "a")

    def test_lone_escape_returns_esc(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "x"]), "esc")

    def test_arrow_up_normalized(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "[", "A"]), "up")

    def test_arrow_down_normalized(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "[", "B"]), "down")

    def test_arrow_right_normalized(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "[", "C"]), "right")

    def test_arrow_left_normalized(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "[", "D"]), "left")

    def test_unknown_escape_sequence_returns_empty_string(self) -> None:
        self.assertEqual(self._read_key_with_stdin(["\x1b", "[", "Z"]), "")


if __name__ == "__main__":
    unittest.main()
