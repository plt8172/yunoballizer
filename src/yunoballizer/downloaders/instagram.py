"""Anonymous (no-login) Instagram account harvesting.

Uses the instaloader library directly instead of shelling out to its CLI:
Instaloader.download_profiles() honors max_count for plain profile targets,
but the instaloader CLI never forwards --count to that codepath (it's only
wired up for #hashtag/:saved/:feed targets there), so the CLI has no way to
cap posts per account.
"""
from __future__ import annotations

import logging
import time

import instaloader

from .. import config

logger = logging.getLogger("yunoballizer.instagram")


def harvest(
    sleep_seconds: int = 20,
    limit: int = 20,
    accounts: list[str] | None = None,
    skip: int = 0,
) -> None:
    if accounts is None:
        accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"
        accounts = config.read_lines(accounts_file)
        if not accounts:
            logger.info("%s is empty, skipping", accounts_file)
            return

    out_dir = config.DATA_DIR / "instagram" / "accounts"
    out_dir.mkdir(parents=True, exist_ok=True)

    loader = instaloader.Instaloader(
        dirname_pattern=str(out_dir / "{target}"),
        quiet=True,
        download_comments=False,
        download_video_thumbnails=False,
    )

    for account in accounts:
        logger.info("[account] checking %s...", account)
        try:
            profile = instaloader.Profile.from_username(loader.context, account)
            remaining_to_skip = skip

            def include_post(_post: object) -> bool:
                nonlocal remaining_to_skip
                if remaining_to_skip:
                    remaining_to_skip -= 1
                    return False
                return True

            loader.download_profiles(
                {profile},
                fast_update=True,
                max_count=skip + limit,
                post_filter=include_post,
            )
        except instaloader.InstaloaderException as e:
            logger.error("Failed to harvest %s: %s", account, e)
        time.sleep(sleep_seconds)
