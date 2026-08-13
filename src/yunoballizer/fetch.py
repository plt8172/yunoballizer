"""Discover account names from the logged-in user's saved Instagram posts.

Fetch deliberately stores no post media or captions.  It reuses an existing
browser session, reads the owners of saved posts, and adds those usernames to
the anonymous download queue.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from . import config

logger = logging.getLogger("yunoballizer.fetch")

DEFAULT_BROWSER = "chrome"


def _authenticated_loader(browser: str) -> Any:
    try:
        import browser_cookie3
        import instaloader
    except ImportError as exc:
        raise SystemExit(
            "Instagram fetch dependencies are missing. Reinstall yunoballizer."
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
    logger.info("Using Instagram session for @%s", username)
    return loader


def _saved_posts(loader: Any) -> Iterable[Any]:
    import instaloader

    return instaloader.Profile.own_profile(loader.context).get_saved_posts()


def run(browser: str = DEFAULT_BROWSER) -> int:
    """Add saved-post authors to accounts.txt without downloading post files."""
    loader = _authenticated_loader(browser)
    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"

    authors = {
        post.owner_username.strip().lower()
        for post in _saved_posts(loader)
        if getattr(post, "owner_username", "").strip()
    }

    added = sum(config.append_line(accounts_file, author) for author in sorted(authors))
    logger.info("Saved-post authors found: %d, newly added: %d", len(authors), added)
    return added
