"""Discover account names from the logged-in user's saved Instagram posts.

Fetch deliberately stores no post media or captions. It reuses the active
Instagram session saved via `yuno auth login`, reads the owners of saved
posts, and adds those usernames to the anonymous download queue.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from . import auth, config

logger = logging.getLogger("yunoballizer.fetch")


def _saved_posts(loader: Any) -> Iterable[Any]:
    import instaloader

    return instaloader.Profile.own_profile(loader.context).get_saved_posts()


def run() -> int:
    """Add saved-post authors to accounts.txt without downloading post files."""
    loader = auth.get_loader()
    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"

    authors = {
        post.owner_username.strip().lower()
        for post in _saved_posts(loader)
        if getattr(post, "owner_username", "").strip()
    }

    added = sum(config.append_line(accounts_file, author) for author in sorted(authors))
    logger.info("Saved-post authors found: %d, newly added: %d", len(authors), added)
    return added
