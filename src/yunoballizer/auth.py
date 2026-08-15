"""Manages Instagram login sessions used by `fetch`.

Instagram cookies are still the underlying auth mechanism -- there's no
practical alternative to that. `auth login` gets those cookies by opening a
dedicated, disposable browser window and waiting for the user to log in
inside it, driving an already-installed Chrome or Edge directly (via
Playwright's `channel` option -- no separate browser download). This is
preferred over reading whatever's already logged into an everyday browser,
since it doesn't require logging that browser in and out of accounts to add
another one.

If that isn't available -- a browser other than Chrome/Edge, or the window
fails to launch for any reason -- login automatically falls back to
importing the session already active in an everyday browser instead.

Either way, instead of fetch silently reusing whatever session it finds on
every run, `auth login` imports it once, asks the user to confirm it's the
right account, and saves it to disk. Multiple accounts can be saved side by
side and switched between with `auth status` / `auth switch`, similar to
`gh auth switch`. Fetch (and anything else that needs Instagram auth) then
just loads whichever saved session is marked active -- no browser needed on
every run.
"""
from __future__ import annotations

import http.cookiejar
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger("yunoballizer.auth")

DEFAULT_BROWSER = "chrome"
INTERACTIVE_LOGIN_TIMEOUT_SECONDS = 300


def _sessions_dir() -> Path:
    return config.CONFIG_DIR / "instagram" / "sessions"


def _active_file() -> Path:
    return config.CONFIG_DIR / "instagram" / "active_session"


def _session_file(username: str) -> Path:
    return _sessions_dir() / f"{username}.session"


def saved_usernames() -> list[str]:
    """Instagram usernames with a saved session, sorted alphabetically."""
    sessions_dir = _sessions_dir()
    if not sessions_dir.exists():
        return []
    return sorted(p.stem for p in sessions_dir.glob("*.session"))


def active_username() -> str | None:
    """The username of the session other commands use by default, if any."""
    active_file = _active_file()
    if not active_file.exists():
        return None
    username = active_file.read_text(encoding="utf-8").strip()
    return username or None


def _set_active(username: str) -> None:
    active_file = _active_file()
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(username + "\n", encoding="utf-8")
    active_file.chmod(0o600)


def _import_from_browser(browser: str) -> Any:
    """Import cookies from an already-logged-in browser and return an authenticated loader."""
    try:
        import browser_cookie3
        import instaloader
    except ImportError as exc:
        raise SystemExit(
            "Instagram auth dependencies are missing. Reinstall yunoballizer."
        ) from exc

    cookie_loader = getattr(browser_cookie3, browser, None)
    if not callable(cookie_loader):
        raise SystemExit(f"Unsupported browser for cookie import: {browser}")

    try:
        cookies = cookie_loader(domain_name=".instagram.com")
        loader = instaloader.Instaloader(quiet=True)
        loader.context.update_cookies(cookies)
        username = loader.test_login()
    except Exception as exc:
        raise SystemExit(f"Could not import the Instagram session from {browser}: {exc}") from exc

    if not username:
        raise SystemExit(
            f"No logged-in Instagram session found in {browser}. "
            "Log in to instagram.com in that browser and try again."
        )

    loader.context.username = username
    return loader


def _cookiejar_from_playwright_cookies(cookies: list[dict]) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    for cookie in cookies:
        domain = cookie.get("domain", "")
        expires = cookie.get("expires")
        jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=cookie["name"],
                value=cookie["value"],
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=bool(domain),
                domain_initial_dot=domain.startswith("."),
                path=cookie.get("path", "/"),
                path_specified=True,
                secure=cookie.get("secure", False),
                expires=int(expires) if expires and expires > 0 else None,
                discard=False,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": cookie.get("httpOnly", False)},
            )
        )
    return jar


# Playwright can drive an already-installed system browser via its `channel`
# option instead of downloading its own bundled Chromium -- but only for
# Chrome/Edge, and browser_cookie3's naming ("edge") doesn't match
# Playwright's channel naming ("msedge"), hence this map.
INTERACTIVE_LOGIN_CHANNELS = {
    "chrome": "chrome",
    "edge": "msedge",
}


def _interactive_browser_login(
    browser: str = DEFAULT_BROWSER,
    timeout_seconds: int = INTERACTIVE_LOGIN_TIMEOUT_SECONDS,
) -> Any:
    """Open a window driving the installed Chrome/Edge, wait for login, and return an authenticated loader.

    Unlike importing from the everyday browser, this doesn't depend on
    whatever account happens to already be logged in there -- the user logs
    in fresh, in a disposable window, for whichever account they want to add.

    Only "chrome" and "edge" are supported (Playwright's `channel` option
    only drives those two browser families). Raises SystemExit -- with a
    message describing what went wrong -- if that's not the case, if the
    browser can't be launched, or if the user doesn't log in within the
    timeout. Callers are expected to catch this and fall back to
    _import_from_browser (see _obtain_session).
    """
    channel = INTERACTIVE_LOGIN_CHANNELS.get(browser)
    if channel is None:
        raise SystemExit(f"Interactive login isn't supported for {browser} (only chrome/edge).")

    try:
        from playwright.sync_api import sync_playwright
        import instaloader
    except ImportError as exc:
        raise SystemExit(f"The 'playwright' package is not available: {exc}") from exc

    print(f"Opening {browser} for Instagram login. Log in there, then return here.")

    with sync_playwright() as p:
        try:
            browser_instance = p.chromium.launch(headless=False, channel=channel)
        except Exception as exc:
            raise SystemExit(f"Could not launch installed {browser}: {exc}") from exc

        try:
            page = browser_instance.new_page()
            page.goto("https://www.instagram.com/accounts/login/")

            deadline = time.monotonic() + timeout_seconds
            cookies: list[dict] = []
            logged_in = False
            while time.monotonic() < deadline:
                cookies = page.context.cookies()
                if any(c["name"] == "sessionid" and c["value"] for c in cookies):
                    logged_in = True
                    break
                page.wait_for_timeout(1000)

            if not logged_in:
                raise SystemExit("Timed out waiting for login in the browser window.")
        finally:
            browser_instance.close()

    loader = instaloader.Instaloader(quiet=True)
    loader.context.update_cookies(_cookiejar_from_playwright_cookies(cookies))
    username = loader.test_login()
    if not username:
        raise SystemExit("Could not detect a logged-in Instagram session after login.")

    loader.context.username = username
    return loader


def _obtain_session(browser: str) -> tuple[Any, str]:
    """Get an authenticated loader, preferring the interactive login window.

    Falls back to importing cookies from an already-logged-in browser when
    interactive login isn't available for `browser`, or fails for any
    reason (not installed, launch error, timeout, ...).
    """
    if browser not in INTERACTIVE_LOGIN_CHANNELS:
        print(f"Interactive login isn't supported for {browser}. Loading browser cookies instead...")
        return _import_from_browser(browser), browser

    try:
        loader = _interactive_browser_login(browser)
        return loader, f"the login window ({browser})"
    except SystemExit as exc:
        print(f"Interactive login failed: {exc}\nLoading browser cookies instead...")
        return _import_from_browser(browser), browser


def login(
    browser: str = DEFAULT_BROWSER,
    assume_yes: bool = False,
    confirm: Callable[[str], str] = input,
) -> str:
    """Obtain a session, confirm it with the user, and save it for reuse.

    Cookie-based import has no way to ask "which account should I use" --
    it only ever sees whichever session is currently active. Asking for
    confirmation here is the closest we can get to a real account picker:
    it stops fetch from silently running as the wrong account just because
    that's what happened to be logged in. Pass assume_yes to skip that
    prompt (e.g. for scripted use).
    """
    loader, source = _obtain_session(browser)
    username = loader.context.username

    if not assume_yes:
        verb = "Re-import" if username in saved_usernames() else "Save"
        answer = confirm(
            f"Detected Instagram session for @{username} in {source}. {verb} and use it? [Y/n] "
        ).strip().lower()
        if answer not in ("", "y", "yes"):
            raise SystemExit("Cancelled.")

    sessions_dir = _sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.chmod(0o700)
    session_file = _session_file(username)
    loader.save_session_to_file(str(session_file))
    session_file.chmod(0o600)
    _set_active(username)
    logger.info("Saved Instagram session for @%s", username)
    return username


def _check_session(username: str) -> tuple[bool, str]:
    """Try loading a saved session, without raising. Returns (is_valid, detail)."""
    try:
        _load_session(username)
    except SystemExit as exc:
        return False, str(exc)
    return True, ""


def status(check: bool = False) -> None:
    """Print saved sessions and mark which one is active.

    With check=True, also loads each saved session to verify it's still
    logged in -- slower (one request per session) but catches sessions
    Instagram has since expired or revoked, before `fetch` hits them.
    """
    usernames = saved_usernames()
    if not usernames:
        print("No saved Instagram sessions. Run `yuno auth login` to add one.")
        return

    active = active_username()
    print("Saved Instagram sessions:")
    for username in usernames:
        marker = "*" if username == active else " "
        if check:
            valid, detail = _check_session(username)
            state = "ok" if valid else f"EXPIRED: {detail}"
            print(f"  {marker} {username} [{state}]")
        else:
            print(f"  {marker} {username}")


def switch(username: str | None = None) -> None:
    """Switch the active session to a previously saved one.

    With no username, cycles to the next saved session (alphabetically
    after the current one, wrapping around) -- similar to `gh auth switch`.
    """
    usernames = saved_usernames()
    if not usernames:
        raise SystemExit("No saved Instagram sessions. Run `yuno auth login` first.")

    if username is None:
        if len(usernames) == 1:
            raise SystemExit(
                f"Only one saved session (@{usernames[0]}) -- nothing to switch to. "
                "Run `yuno auth login` to add another."
            )
        current = active_username()
        index = (usernames.index(current) + 1) % len(usernames) if current in usernames else 0
        username = usernames[index]
    elif username not in usernames:
        raise SystemExit(
            f"No saved session for @{username}. Run `yuno auth login` first, "
            "or check `yuno auth status` for saved usernames."
        )

    _set_active(username)
    print(f"Switched active Instagram session to @{username}.")


def logout(username: str | None = None) -> None:
    """Remove a saved session, defaulting to the active one."""
    target = username or active_username()
    if not target:
        raise SystemExit("No active session to remove. Pass a username, or check `yuno auth status`.")

    session_file = _session_file(target)
    if not session_file.exists():
        raise SystemExit(f"No saved session for @{target}.")

    session_file.unlink()
    if active_username() == target:
        _active_file().unlink(missing_ok=True)
    print(f"Removed saved Instagram session for @{target}.")


def _load_session(username: str) -> Any:
    """Load a specific saved session from disk. Raises SystemExit if unavailable or expired."""
    try:
        import instaloader
    except ImportError as exc:
        raise SystemExit(
            "Instagram auth dependencies are missing. Reinstall yunoballizer."
        ) from exc

    session_file = _session_file(username)
    if not session_file.exists():
        raise SystemExit(
            f"Saved session for @{username} is missing on disk. Run `yuno auth login` again."
        )

    loader = instaloader.Instaloader(quiet=True)
    try:
        loader.load_session_from_file(username, str(session_file))
    except Exception as exc:
        raise SystemExit(f"Could not load the saved Instagram session for @{username}: {exc}") from exc

    return loader


def get_loader() -> Any:
    """Load the active saved session, for use by commands like fetch."""
    username = active_username()
    if not username:
        raise SystemExit(
            "No active Instagram session. Run `yuno auth login` first, "
            "then `yuno auth status` to confirm it's active."
        )

    loader = _load_session(username)
    logger.info("Using Instagram session for @%s", username)
    return loader
