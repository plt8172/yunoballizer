from __future__ import annotations

import io
import stat
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


class CookiejarFromPlaywrightCookiesTests(unittest.TestCase):
    def test_converts_cookie_fields(self) -> None:
        jar = auth._cookiejar_from_playwright_cookies(
            [
                {
                    "name": "sessionid",
                    "value": "abc123",
                    "domain": ".instagram.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "expires": -1,
                }
            ]
        )
        cookies = list(jar)
        self.assertEqual(len(cookies), 1)
        cookie = cookies[0]
        self.assertEqual(cookie.name, "sessionid")
        self.assertEqual(cookie.value, "abc123")
        self.assertEqual(cookie.domain, ".instagram.com")
        self.assertTrue(cookie.secure)
        self.assertIsNone(cookie.expires)


class _FakePage:
    def __init__(self, cookies_sequence: list[list[dict]]) -> None:
        self._cookies_sequence = cookies_sequence
        self._index = 0
        self.goto_calls: list[str] = []
        self.wait_calls: list[int] = []
        self.context = SimpleNamespace(cookies=self._cookies)

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)

    def _cookies(self) -> list[dict]:
        if self._index < len(self._cookies_sequence):
            result = self._cookies_sequence[self._index]
            self._index += 1
        else:
            result = self._cookies_sequence[-1]
        return result

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_calls.append(ms)


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    def new_page(self) -> _FakePage:
        return self._page

    def close(self) -> None:
        self.closed = True


def _fake_sync_playwright_module(page: _FakePage, browser: _FakeBrowser) -> SimpleNamespace:
    chromium = SimpleNamespace(launch=lambda headless=False: browser)
    playwright = SimpleNamespace(chromium=chromium)

    class _Cm:
        def __enter__(self):
            return playwright

        def __exit__(self, *args):
            return False

    return SimpleNamespace(sync_playwright=lambda: _Cm())


class InteractiveBrowserLoginTests(unittest.TestCase):
    def test_returns_loader_once_sessionid_cookie_appears(self) -> None:
        session_cookie = {
            "name": "sessionid", "value": "abc123", "domain": ".instagram.com",
            "path": "/", "secure": True, "httpOnly": True, "expires": -1,
        }
        page = _FakePage(cookies_sequence=[[], [session_cookie]])
        browser = _FakeBrowser(page)
        sync_api = _fake_sync_playwright_module(page, browser)

        context = SimpleNamespace(username=None)
        captured_jar = {}
        context.update_cookies = lambda jar: captured_jar.__setitem__("jar", jar)
        loader = SimpleNamespace(context=context, test_login=lambda: "carol")
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: loader)

        with patch.dict(
            "sys.modules",
            {
                "playwright": SimpleNamespace(),
                "playwright.sync_api": sync_api,
                "instaloader": instaloader,
            },
        ):
            result = auth._interactive_browser_login()

        self.assertIs(result, loader)
        self.assertEqual(context.username, "carol")
        self.assertTrue(browser.closed)
        self.assertIn("sessionid", [c.name for c in captured_jar["jar"]])

    def test_times_out_when_no_login_happens(self) -> None:
        page = _FakePage(cookies_sequence=[[]])
        browser = _FakeBrowser(page)
        sync_api = _fake_sync_playwright_module(page, browser)
        instaloader = SimpleNamespace(Instaloader=lambda **kwargs: self.fail("should not be reached"))

        with patch.dict(
            "sys.modules",
            {
                "playwright": SimpleNamespace(),
                "playwright.sync_api": sync_api,
                "instaloader": instaloader,
            },
        ):
            with self.assertRaises(SystemExit):
                auth._interactive_browser_login(timeout_seconds=0)

        self.assertTrue(browser.closed)

    def test_missing_playwright_raises_helpful_error(self) -> None:
        with patch.dict("sys.modules", {"playwright.sync_api": None, "playwright": None}):
            with self.assertRaises(SystemExit):
                auth._interactive_browser_login()


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

    def test_login_interactive_uses_login_window_instead_of_browser_cookies(self) -> None:
        loader = self._fake_loader("carol")
        with (
            patch.object(auth, "_interactive_browser_login", return_value=loader) as mock_interactive,
            patch.object(auth, "_import_from_browser") as mock_cookie_import,
        ):
            username = auth.login(interactive=True, confirm=lambda prompt: "y")

        mock_interactive.assert_called_once()
        mock_cookie_import.assert_not_called()
        self.assertEqual(username, "carol")
        self.assertEqual(auth.active_username(), "carol")

    def test_login_assume_yes_skips_confirmation(self) -> None:
        loader = self._fake_loader("alice")

        def confirm_should_not_be_called(prompt: str) -> str:
            self.fail("confirm() should not be called when assume_yes=True")

        with patch.object(auth, "_import_from_browser", return_value=loader):
            username = auth.login(browser="chrome", assume_yes=True, confirm=confirm_should_not_be_called)

        self.assertEqual(username, "alice")
        self.assertEqual(auth.active_username(), "alice")

    def test_login_sets_restrictive_permissions(self) -> None:
        loader = self._fake_loader("alice")
        with patch.object(auth, "_import_from_browser", return_value=loader):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        session_mode = stat.S_IMODE(auth._session_file("alice").stat().st_mode)
        dir_mode = stat.S_IMODE(auth._sessions_dir().stat().st_mode)
        active_mode = stat.S_IMODE(auth._active_file().stat().st_mode)

        self.assertEqual(session_mode, 0o600)
        self.assertEqual(dir_mode, 0o700)
        self.assertEqual(active_mode, 0o600)

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

    def test_status_check_flags_expired_sessions(self) -> None:
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("alice")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")
        with patch.object(auth, "_import_from_browser", return_value=self._fake_loader("bob")):
            auth.login(browser="chrome", confirm=lambda prompt: "y")

        def load_session_from_file(username: str, path: str) -> None:
            if username == "bob":
                raise Exception("session expired")

        instaloader = SimpleNamespace(
            Instaloader=lambda **kwargs: SimpleNamespace(load_session_from_file=load_session_from_file)
        )

        out = io.StringIO()
        with patch.dict("sys.modules", {"instaloader": instaloader}), redirect_stdout(out):
            auth.status(check=True)

        output = out.getvalue()
        self.assertIn("alice [ok]", output)
        self.assertIn("bob [EXPIRED", output)
        self.assertIn("session expired", output)

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
