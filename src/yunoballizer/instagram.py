"""Anonymous (no-login) Instagram account harvesting.

instaloader's internal API has shifted across versions, so instead of calling
library functions directly, we shell out to its well-tested CLI interface.
"""
from __future__ import annotations

import logging
import subprocess
import time

from . import config

logger = logging.getLogger("yunoballizer.instagram")


def harvest(sleep_seconds: int = 20) -> None:
    accounts = config.read_lines("accounts.txt")
    if not accounts:
        logger.info("accounts.txt is empty, skipping")
        return

    out_dir = config.DATA_DIR / "instagram" / "accounts"
    out_dir.mkdir(parents=True, exist_ok=True)

    for account in accounts:
        logger.info("[account] checking %s...", account)
        try:
            subprocess.run(
                [
                    "instaloader",
                    "--fast-update",
                    "--dirname-pattern", str(out_dir / "{target}"),
                    account,
                ],
                check=False,
            )
        except FileNotFoundError:
            logger.error("instaloader is not installed: pip install instaloader")
            return
        time.sleep(sleep_seconds)
