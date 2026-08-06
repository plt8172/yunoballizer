"""Login-required fetching of saved posts and hashtag search results.

Authenticates via --load-cookies (reusing an already-logged-in browser
session) instead of instaloader's own --login flow. Instagram treats a
fresh programmatic --login as a different, untrusted "device" from the
browser, so completing the checkpoint verification in a browser doesn't
actually clear it for --login — it's a long-standing, essentially
unresolved loop (see instaloader issues #2590, #1740, #798, #1642, #1787).
Reusing real browser cookies sidesteps the checkpoint entirely since no
new login is attempted.

Recommended to run manually every 1-2 weeks rather than putting it in cron.
"""
from __future__ import annotations

import logging
import subprocess
import time

from . import config

logger = logging.getLogger("yunoballizer.fetch")

DEFAULT_BROWSER = "chrome"


def run(sleep_seconds: int = 20, browser: str = DEFAULT_BROWSER) -> None:
    saved_dir = config.DATA_DIR / "instagram" / "saved"
    hashtags_dir = config.DATA_DIR / "instagram" / "hashtags"
    saved_dir.mkdir(parents=True, exist_ok=True)
    hashtags_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[saved posts] checking...")
    subprocess.run(
        [
            "instaloader",
            "--fast-update",
            "--no-video-thumbnails",
            "--load-cookies", browser,
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
                "--no-video-thumbnails",
                "--load-cookies", browser,
                "--dirname-pattern", str(hashtags_dir / tag / "{profile}"),
                f"#{tag}",
            ],
            check=False,
        )
        time.sleep(sleep_seconds)
