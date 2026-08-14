"""Builds a content profile from downloaded Instagram captions."""
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
    captions_dir = config.SOURCES_DIR / "instagram"
    captions = []
    if captions_dir.exists():
        for txt_file in captions_dir.glob("*/*/caption.txt"):
            try:
                captions.append(txt_file.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

    if not captions:
        raise SystemExit(
            f"No downloaded Instagram captions found: {captions_dir}\n"
            "Run `yunoballizer download` first."
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

    profile_path = config.DERIVED_DIR / PROFILE_FILENAME
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
