"""Builds a taste profile (taste_profile.json) from saved post captions."""
from __future__ import annotations

import json
import re
from collections import Counter

from . import config

HASHTAG_RE = re.compile(r"#(\w+)")
WORD_RE = re.compile(r"[A-Za-z가-힣]{2,}")
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "have", "just", "your",
    "from", "are", "was", "were", "you", "all", "not", "but", "what",
}

PROFILE_FILENAME = "taste_profile.json"


def build() -> dict:
    saved_dir = config.DATA_DIR / "instagram" / "saved"
    captions = []
    if saved_dir.exists():
        for txt_file in saved_dir.rglob("*.txt"):
            try:
                captions.append(txt_file.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

    if not captions:
        raise SystemExit(
            f"No saved post captions found: {saved_dir}\n"
            "Run `yunoballizer fetch` first to fetch your saved posts."
        )

    hashtag_counter: Counter[str] = Counter()
    word_counter: Counter[str] = Counter()

    for caption in captions:
        hashtag_counter.update(h.lower() for h in HASHTAG_RE.findall(caption))
        word_counter.update(
            w.lower() for w in WORD_RE.findall(caption)
            if w.lower() not in STOPWORDS and len(w) > 1
        )

    profile = {
        "source_post_count": len(captions),
        "top_hashtags": [h for h, _ in hashtag_counter.most_common(40)],
        "top_keywords": [w for w, _ in word_counter.most_common(60)],
    }

    profile_path = config.CONFIG_DIR / PROFILE_FILENAME
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
