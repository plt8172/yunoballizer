"""Auto-expands accounts.txt from signals in already-fetched content.

No extra network requests are made, so growing the account pool this way
doesn't add any additional risk.
"""
from __future__ import annotations

import json
import logging
import lzma
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


def scan_hashtag_authors() -> int:
    hashtags_dir = config.DATA_DIR / "instagram" / "hashtags"
    if not hashtags_dir.exists():
        return 0

    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"
    new_accounts = set()
    for tag_dir in hashtags_dir.iterdir():
        if not tag_dir.is_dir():
            continue
        for owner_dir in tag_dir.iterdir():
            if owner_dir.is_dir():
                new_accounts.add(owner_dir.name)

    added = 0
    for name in sorted(new_accounts):
        if config.append_line(accounts_file, name):
            added += 1
            logger.debug("New account found: %s (posted under a monitored hashtag)", name)

    return added


def scan_saved_authors() -> int:
    saved_dir = config.DATA_DIR / "instagram" / "saved"
    if not saved_dir.exists():
        return 0

    accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"
    authors = set()
    for meta_file in saved_dir.rglob("*.json.xz"):
        try:
            with lzma.open(meta_file) as f:
                data = json.load(f)
            authors.add(data["node"]["owner"]["username"])
        except Exception:
            continue

    added = 0
    for name in sorted(authors):
        if config.append_line(accounts_file, name):
            added += 1
            logger.debug("New account found: %s (authored a saved post)", name)

    return added
