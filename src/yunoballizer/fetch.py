"""Login-required fetching of saved posts and hashtag search results.

Saved posts and hashtag search require login under Instagram's current
policy, so this is the only module that logs in. Username is read from
IG_USERNAME if set, otherwise prompted for; password/2FA are always
prompted interactively by instaloader on first login, then cached in a
session file.

Recommended to run manually every 1-2 weeks rather than putting it in cron.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

from . import config

logger = logging.getLogger("yunoballizer.fetch")


def run(sleep_seconds: int = 20) -> None:
    username = os.environ.get("IG_USERNAME") or input("Instagram username: ").strip()
    if not username:
        raise SystemExit("No username given.")

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

    hashtags = config.read_lines(config.CONFIG_DIR / "instagram" / "hashtags.txt")
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
