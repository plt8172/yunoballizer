"""Auto-expands accounts.txt from mentions in downloaded captions.

No extra network requests are made, so growing the account pool this way
doesn't add any additional risk.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from . import config

logger = logging.getLogger("yunoballizer.expand")

MENTION_RE = re.compile(r"@([A-Za-z0-9_.]{2,30})")


def scan_caption_mentions() -> int:
    scan_dir = config.DATA_DIR / "instagram" / "accounts"
    if not scan_dir.exists():
        return 0

    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"
    counts: Counter[str] = Counter()

    for txt_file in scan_dir.rglob("*.txt"):
        try:
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for mention in MENTION_RE.findall(text):
            counts[mention.lower()] += 1

    added = 0
    for name in sorted(counts):
        if config.append_line(accounts_file, name):
            added += 1
            logger.debug("New account found: %s (mentioned %d times in captions)", name, counts[name])

    return added
