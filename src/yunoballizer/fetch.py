"""Discover account names from the logged-in user's Instagram, from one or
more sources, and add them to the anonymous download queue.

Fetch deliberately stores no post media or captions -- it reuses the active
Instagram session saved via `yuno auth login`, reads accounts out of the
selected source(s), and adds those usernames to accounts.txt.
"""
from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable
from typing import Any

from . import auth, config

logger = logging.getLogger("yunoballizer.fetch")

# Sources instaloader (and Instagram's own private web/app API underneath
# it) can actually read. "liked" and "reposted" are not here on purpose --
# see _UNSUPPORTED_SOURCES.
SOURCES = ("saved", "following")

_UNSUPPORTED_SOURCES = {
    "liked": (
        "Instagram removed API access to a user's liked posts years ago, "
        "for official and unofficial clients alike -- there is no endpoint "
        "left anywhere to read this from."
    ),
    "reposted": (
        "Instagram's repost feature has no endpoint exposed anywhere yet "
        "(official or private) -- instaloader has no support for it."
    ),
}


def _saved_posts(loader: Any) -> Iterable[Any]:
    import instaloader

    return instaloader.Profile.own_profile(loader.context).get_saved_posts()


def _followees(loader: Any) -> Iterable[Any]:
    import instaloader

    return instaloader.Profile.own_profile(loader.context).get_followees()


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


def _saved_authors(loader: Any, limit: int | None) -> set[str]:
    posts = _saved_posts(loader)
    if limit is not None:
        posts = itertools.islice(posts, limit)
    owner_ids = {post.owner_id for post in posts}

    authors = set()
    for owner_id in owner_ids:
        username = _resolve_username(loader, owner_id)
        if username and username.strip():
            authors.add(username.strip().lower())
    return authors


def _following_authors(loader: Any, limit: int | None) -> set[str]:
    # Unlike saved posts, the followees listing already includes each
    # account's username -- no per-account resolution request needed.
    followees = _followees(loader)
    if limit is not None:
        followees = itertools.islice(followees, limit)
    return {
        profile.username.strip().lower()
        for profile in followees
        if getattr(profile, "username", "").strip()
    }


def _validate_sources(sources: list[str]) -> None:
    unsupported = [s for s in sources if s in _UNSUPPORTED_SOURCES]
    if unsupported:
        reasons = "\n".join(f"  - {s}: {_UNSUPPORTED_SOURCES[s]}" for s in unsupported)
        raise SystemExit(f"Unsupported source(s):\n{reasons}")

    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        raise SystemExit(
            f"Unknown source(s): {', '.join(unknown)}. Choose from: {', '.join(SOURCES)}"
        )


def run(limit: int | None = None, sync: bool = False, sources: list[str] | None = None) -> int:
    """Add accounts from the selected source(s) to accounts.txt.

    sources defaults to ["saved"]; pass e.g. ["saved", "following"] to pull
    from more than one. limit caps how many items are read *per source*
    (default: no limit). With sync=True, accounts.txt is made to match
    exactly what was found this run -- any account not in that result gets
    removed, not just new ones added.
    """
    sources = sources or ["saved"]
    _validate_sources(sources)

    loader = auth.get_loader()
    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"

    authors: set[str] = set()
    if "saved" in sources:
        authors |= _saved_authors(loader, limit)
    if "following" in sources:
        authors |= _following_authors(loader, limit)

    if sync:
        stale = sorted(set(config.read_lines(accounts_file)) - authors)
        for name in stale:
            config.remove_line(accounts_file, name)
        added = sum(config.append_line(accounts_file, name) for name in sorted(authors))
        logger.info("Accounts found: %d, added: %d, removed: %d", len(authors), added, len(stale))
        if stale:
            logger.info("Removed (no longer in selected source(s)): %s", ", ".join(stale))
        return added

    added = sum(config.append_line(accounts_file, author) for author in sorted(authors))
    logger.info("Accounts found: %d, newly added: %d", len(authors), added)
    return added
