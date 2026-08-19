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


def _resolve_username(loader: Any, owner_id: int) -> str | None:
    """Resolve a saved post's owner id to a username.

    The saved-posts listing gives each post's owner id but not their
    username. Reading `post.owner_username` directly would make instaloader
    fetch that post's *entire* metadata just to get it -- one extra request
    per post. Profile.from_id() resolves an id with a single lighter
    request and instaloader caches the result, so posts sharing an owner
    (common, since saving several posts from the same account is normal)
    only cost one request total instead of one per post.
    """
    import instaloader

    try:
        return instaloader.Profile.from_id(loader.context, owner_id).username
    except Exception:
        logger.warning("Could not resolve saved-post owner id %s, skipping", owner_id)
        return None


def run() -> int:
    """Add saved-post authors to accounts.txt without downloading post files."""
    loader = auth.get_loader()
    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"

    owner_ids = {post.owner_id for post in _saved_posts(loader)}
    authors = set()
    for owner_id in owner_ids:
        username = _resolve_username(loader, owner_id)
        if username and username.strip():
            authors.add(username.strip().lower())

    added = sum(config.append_line(accounts_file, author) for author in sorted(authors))
    logger.info("Saved-post authors found: %d, newly added: %d", len(authors), added)
    return added
