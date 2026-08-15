from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yunoballizer import auth


class ImportFromBrowserTests(unittest.TestCase):
    def test_imports_browser_session(self) -> None:
        cookie_jar = object()
        context = SimpleNamespace(
            username=None,
            update_cookies=lambda cookies: self.assertIs(cookies, cookie_jar),
        )
        loader = SimpleNamespace(context=context, test_login=lambda: "viewer")
        browser_cookie3 = SimpleNamespace(
            chrome=lambda **kwargs: cookie_jar
            if kwargs == {"domain_name": ".instagram.com"}
            else self.fail("unexpected cookie arguments")
        )
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: loader)

        with patch.dict(
            "sys.modules",
            {"browser_cookie3": browser_cookie3, "instaloader": instaloader},
        ):
            result = auth._import_from_browser("chrome")

        self.assertIs(result, loader)
        self.assertEqual(context.username, "viewer")

    def test_no_session_found_raises(self) -> None:
        context = SimpleNamespace(username=None, update_cookies=lambda cookies: None)
        loader = SimpleNamespace(context=context, test_login=lambda: None)
        browser_cookie3 = SimpleNamespace(chrome=lambda **kwargs: object())
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: loader)

        with patch.dict(
            "sys.modules",
            {"browser_cookie3": browser_cookie3, "instaloader": instaloader},
        ):
            with self.assertRaises(SystemExit):
                auth._import_from_browser("chrome")

    def test_unsupported_browser_raises(self) -> None:
        browser_cookie3 = SimpleNamespace()
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: object())

        with patch.dict(
            "sys.modules",
            {"browser_cookie3": browser_cookie3, "instaloader": instaloader},
        ):
            with self.assertRaises(SystemExit):
                auth._import_from_browser("nonexistent-browser")


class AuthSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        config_dir = Path(self._tmpdir.name)
        patcher = patch.object(auth.config, "CONFIG_DIR", config_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_loader(self, username: str) -> SimpleNamespace:
        saved: dict[str, str] = {}

        def save_session_to_file(path: str) -> None:
            saved["path"] = path
            Path(path).write_text("fake-session", encoding="utf-8")

        context = SimpleNamespace(username=username)
        return SimpleNamespace(
            context=context,
            save_session_to_file=save_session_to_file,
            _saved=saved,
        )

    def test_login_saves_session_and_sets_active(self) -> None:
        loader = self._fake_loader("alice")
        with patch.object(auth, "_import_from_browser", return_value=loader):
            username = auth.login(browser="chrome", confirm=lambda prompt: "y")

        self.assertEqual(username, "alice")
        self.assertEqual(auth.saved_usernames(), ["alice"])
        self.assertEqual(auth.active_username(), "alice")
        self.assertEqual(loader._saved["path"], str(auth._session_file("alice")))

    def test_login_declined_raises_and_saves_nothing(self) -> None:
        loader = self._fake_loader("alice")
        with patch.object(auth, "_import_from_browser", return_value=loader):
            with self.assertRaises(SystemExit):
                auth.login(browser="chrome", confirm=lambda prompt: "n")

        self.assertEqual(auth.saved_usernames(), [])
        self.assertIsNone(auth.active_username())

    def test_second_login_adds_session_without_switching_active(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("bob")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        self.assertEqual(auth.saved_usernames(), ["alice", "bob"])
        self.assertEqual(auth.active_username(), "bob")

    def test_status_marks_active_session(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("bob")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        out = io.StringIO()
        with redirect_stdout(out):
            auth.status()

        output = out.getvalue()
        self.assertIn("* bob", output)
        self.assertIn("  alice", output)

    def test_status_with_no_sessions(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            auth.status()

        self.assertIn("No saved Instagram sessions", out.getvalue())

    def test_switch_updates_active_session(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("bob")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        auth.switch("alice")

        self.assertEqual(auth.active_username(), "alice")

    def test_switch_unknown_username_raises(self) -> None:
        with self.assertRaises(SystemExit):
            auth.switch("nobody")

    def test_logout_removes_active_session(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        auth.logout()

        self.assertEqual(auth.saved_usernames(), [])
        self.assertIsNone(auth.active_username())

    def test_logout_specific_username_keeps_other_sessions_active(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("bob")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        auth.logout("alice")

        self.assertEqual(auth.saved_usernames(), ["bob"])
        self.assertEqual(auth.active_username(), "bob")

    def test_logout_with_no_active_session_raises(self) -> None:
        with self.assertRaises(SystemExit):
            auth.logout()

    def test_get_loader_with_no_active_session_raises(self) -> None:
        with self.assertRaises(SystemExit):
            auth.get_loader()

    def test_get_loader_loads_active_session(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        loaded_calls = []
        loader = SimpleNamespace(
            load_session_from_file=lambda username, path: loaded_calls.append((username, path))
        )
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: loader)

        with patch.dict("sys.modules", {"instaloader": instaloader}):
            result = auth.get_loader()

        self.assertIs(result, loader)
        self.assertEqual(loaded_calls, [("alice", str(auth._session_file("alice")))])


if __name__ == "__main__":
    unittest.main()
