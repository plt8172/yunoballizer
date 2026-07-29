"""Login-required 'discovery' logic.

Saved posts and hashtag search require login under Instagram's current policy.
So only this module uses login, and it auto-adds the authors of discovered
posts to accounts.txt so that anonymous harvesting (instagram.py) takes over
from there.

Recommended to run manually every 1-2 weeks rather than putting it in cron.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

from . import config

logger = logging.getLogger("yunoballizer.discover")


def run(sleep_seconds: int = 20) -> None:
    username = os.environ.get("IG_USERNAME")
    if not username:
        raise SystemExit(
            "Set the IG_USERNAME environment variable (e.g. export IG_USERNAME=myid)\n"
            "The first time, log in once with `instaloader --login=your_username` "
            "so a session file gets saved."
        )

    saved_dir = config.DATA_DIR / "instagram" / "saved"
    hashtags_dir = config.DATA_DIR / "instagram" / "hashtags"
    saved_dir.mkdir(parents=True, exist_ok=True)
    hashtags_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[saved posts] checking...")
    subprocess.run(
        [
            "instaloader",
            "--fast-update",
            "--login", username,
            "--dirname-pattern", str(saved_dir / "{target}"),
            ":saved",
        ],
        check=False,
    )

    hashtags = config.read_lines("hashtags.txt")
    for tag in hashtags:
        logger.info("[hashtag] checking #%s...", tag)
        subprocess.run(
            [
                "instaloader",
                "--fast-update",
                "--login", username,
                "--dirname-pattern", str(hashtags_dir / tag / "{profile}"),
                f"#{tag}",
            ],
            check=False,
        )
        time.sleep(sleep_seconds)

    # Auto-add the post authors' folder names to accounts.txt
    new_accounts = set()
    if hashtags_dir.exists():
        for tag_dir in hashtags_dir.iterdir():
            if not tag_dir.is_dir():
                continue
            for owner_dir in tag_dir.iterdir():
                if owner_dir.is_dir():
                    new_accounts.add(owner_dir.name)

    added = 0
    for name in sorted(new_accounts):
        if config.append_line("accounts.txt", name):
            added += 1
    logger.info("New accounts discovered and added to accounts.txt: %d", added)
