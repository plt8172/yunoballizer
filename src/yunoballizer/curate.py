"""Curates newly harvested posts against the content profile using rules + AI."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

from . import config
from .profile import PROFILE_FILENAME

logger = logging.getLogger("yunoballizer.curate")

LOG_FILENAME = "curation_log.json"

SOURCE_SUBDIRS = [
    ("instagram", "accounts"),
    ("other",),
    ("youtube", "channels"),
    ("youtube", "hashtags"),
    ("tiktok", "accounts"),
]

LOW_THRESHOLD = 0.05
HIGH_THRESHOLD = 0.25

HASHTAG_RE = re.compile(r"#(\w+)")
WORD_RE = re.compile(r"[A-Za-z가-힣]{2,}")
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".mp4", ".webm"}


def _load_profile() -> dict:
    path = config.CONFIG_DIR / PROFILE_FILENAME
    if not path.exists():
        raise SystemExit("taste_profile.json not found. Run `yunoballizer profile` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_log() -> dict:
    path = config.CONFIG_DIR / LOG_FILENAME
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_log(log: dict) -> None:
    path = config.CONFIG_DIR / LOG_FILENAME
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _rule_score(caption: str, profile: dict) -> float:
    hashtags = {h.lower() for h in HASHTAG_RE.findall(caption)}
    words = {w.lower() for w in WORD_RE.findall(caption)}
    top_hashtags = set(profile.get("top_hashtags", []))
    top_keywords = set(profile.get("top_keywords", []))

    hashtag_hits = len(hashtags & top_hashtags)
    keyword_hits = len(words & top_keywords)
    total_signals = len(hashtags) + len(words) or 1
    return (hashtag_hits * 2 + keyword_hits) / total_signals


def _ask_claude(caption: str, profile: dict) -> bool:
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed: pip install 'yunoballizer[curate]'")
        return False

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping AI judgment for this item.")
        return False

    client = anthropic.Anthropic(api_key=api_key)
    top_hashtags = ", ".join(profile.get("top_hashtags", [])[:15])
    top_keywords = ", ".join(profile.get("top_keywords", [])[:20])

    prompt = f"""Below are taste signals extracted from posts a user has previously saved on Instagram.
Frequently occurring hashtags: {top_hashtags}
Frequently occurring keywords: {top_keywords}

Here is the caption of a newly discovered post:
---
{caption[:800]}
---

Is this user likely to enjoy this post? Answer with a single word, "yes" or "no"."""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = "".join(
            block.text for block in resp.content if block.type == "text"
        ).strip().lower()
        return answer.startswith("y")
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return False


def _find_caption(media_path: Path) -> str:
    txt_path = media_path.with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8", errors="ignore")

    json_path = Path(str(media_path.with_suffix(""))).with_suffix(".info.json")
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
            return data.get("description", "") or data.get("title", "")
        except Exception:
            return ""
    return ""


def run() -> None:
    profile = _load_profile()
    log = _load_log()
    curated_dir = config.DATA_DIR / "curated"
    curated_dir.mkdir(parents=True, exist_ok=True)

    checked = kept = 0

    for parts in SOURCE_SUBDIRS:
        source_dir = config.DATA_DIR.joinpath(*parts)
        if not source_dir.exists():
            continue
        for media_path in source_dir.rglob("*"):
            if media_path.suffix.lower() not in MEDIA_EXTS:
                continue
            key = str(media_path)
            if key in log:
                continue

            caption = _find_caption(media_path)
            score = _rule_score(caption, profile)
            checked += 1

            if score >= HIGH_THRESHOLD:
                decision = "keep"
            elif score <= LOW_THRESHOLD:
                decision = "skip"
            else:
                decision = "keep" if _ask_claude(caption, profile) else "skip"

            log[key] = {"score": round(score, 3), "decision": decision}

            if decision == "keep":
                shutil.copy2(media_path, curated_dir / media_path.name)
                kept += 1

    _save_log(log)
    logger.info("Reviewed: %d, kept: %d -> %s", checked, kept, curated_dir)
