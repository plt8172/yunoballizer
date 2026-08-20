"""Discover Instagram accounts from selected posts without inventing handles."""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from .. import config, llm
from ..storage import find_caption
from . import accounts, auth, select

logger = logging.getLogger(__name__)

MENTION_RE = re.compile(r"@([A-Za-z0-9_.]{2,30})")
HANDLE_RE = re.compile(r"@?([A-Za-z0-9_.]{2,30})")
MAX_SIMILAR_PER_SEED = 10
MAX_LLM_CANDIDATES = 50
MAX_SEED_CAPTIONS = 15


@dataclass
class Candidate:
    username: str
    mentions: int = 0
    similar_to: set[str] = field(default_factory=set)
    full_name: str = ""
    biography: str = ""

    @property
    def signal_count(self) -> int:
        return self.mentions + len(self.similar_to)

    def evidence(self) -> str:
        parts = []
        if self.similar_to:
            parts.append("similar to " + ", ".join(f"@{name}" for name in sorted(self.similar_to)))
        if self.mentions:
            parts.append(f"mentioned {self.mentions} time(s)")
        return "; ".join(parts)


def _selected_instagram_posts() -> list[tuple[str, str]]:
    posts: dict[tuple[str, str], str] = {}
    for key, entry in select.selected_state().items():
        if entry.get("status") != "selected":
            continue
        path = config.DOWNLOADED_DIR / key
        platform, account, post_id, _filename = select._describe(path)
        if platform != "instagram" or not account:
            continue
        posts.setdefault((account, post_id), find_caption(path).strip())
    return [(account, caption) for (account, _post_id), caption in posts.items()]


def _mention_candidates(posts: list[tuple[str, str]]) -> dict[str, Candidate]:
    counts: Counter[str] = Counter()
    for _account, caption in posts:
        counts.update(name.lower() for name in MENTION_RE.findall(caption))
    return {
        username: Candidate(username=username, mentions=count)
        for username, count in counts.items()
    }


def _add_similar_candidates(candidates: dict[str, Candidate], seeds: set[str]) -> None:
    if not auth.active_username():
        logger.warning(
            "No active Instagram session; skipping similar-account lookup and using caption mentions only."
        )
        return

    try:
        import instaloader
    except ImportError as exc:
        raise SystemExit("Instagram dependencies are missing. Reinstall yunoballizer.") from exc

    loader = auth.get_loader()
    for seed in sorted(seeds):
        try:
            profile = instaloader.Profile.from_username(loader.context, seed)
            for index, similar in enumerate(profile.get_similar_accounts()):
                if index >= MAX_SIMILAR_PER_SEED:
                    break
                username = similar.username.lower()
                candidate = candidates.setdefault(username, Candidate(username=username))
                candidate.similar_to.add(seed)
                candidate.full_name = getattr(similar, "full_name", "") or ""
                candidate.biography = getattr(similar, "biography", "") or ""
        except Exception as exc:
            logger.warning("Could not retrieve accounts similar to @%s: %s", seed, exc)


def _rank(candidates: dict[str, Candidate]) -> list[Candidate]:
    return sorted(
        candidates.values(),
        key=lambda item: (-item.signal_count, -len(item.similar_to), -item.mentions, item.username),
    )


def _llm_select(
    ranked: list[Candidate], posts: list[tuple[str, str]], limit: int
) -> list[Candidate]:
    api_key = llm.resolve_api_key()
    if not api_key:
        logger.warning("No LLM profile configured; ranking candidates by discovery evidence only.")
        return ranked[:limit]

    captions = [caption[:600] for _account, caption in posts if caption][:MAX_SEED_CAPTIONS]
    taste = "\n".join(f"- {caption}" for caption in captions) or "(selected posts have no captions)"
    pool = ranked[:MAX_LLM_CANDIDATES]
    candidate_lines = []
    for candidate in pool:
        details = [candidate.evidence()]
        if candidate.full_name:
            details.append(candidate.full_name)
        if candidate.biography:
            details.append(candidate.biography[:200])
        candidate_lines.append(f"- @{candidate.username} | " + " | ".join(part for part in details if part))

    prompt = f"""Select up to {limit} Instagram accounts that best match the user's selected posts.
Only choose handles from the candidate list. Never create or modify a handle.
Return one chosen @handle per line and nothing else.

Selected-post captions:
{taste}

Candidates:
{chr(10).join(candidate_lines)}"""
    try:
        answer = llm.call(prompt, api_key=api_key, max_tokens=200, temperature=0)
    except llm.LlmError as exc:
        logger.warning("LLM candidate selection failed; using evidence ranking instead: %s", exc)
        return pool[:limit]

    allowed = {candidate.username: candidate for candidate in pool}
    chosen = []
    seen = set()
    for line in answer.splitlines():
        match = HANDLE_RE.fullmatch(line.strip())
        if not match:
            continue
        username = match.group(1).lower()
        if username in allowed and username not in seen:
            chosen.append(allowed[username])
            seen.add(username)
        if len(chosen) >= limit:
            break
    if not chosen:
        logger.warning("LLM returned no valid candidate handles; using evidence ranking instead.")
        return pool[:limit]
    return chosen


def run(*, limit: int = 10, add: bool = False) -> list[Candidate]:
    posts = _selected_instagram_posts()
    if not posts:
        raise SystemExit("Discover needs selected Instagram posts. Run `yuno select` first.")

    seeds = {account.lower() for account, _caption in posts}
    candidates = _mention_candidates(posts)
    _add_similar_candidates(candidates, seeds)

    monitored = set(accounts.list_accounts("instagram")["instagram"])
    excluded = seeds | {name.lstrip("@").lower() for name in monitored}
    candidates = {name: item for name, item in candidates.items() if name not in excluded}
    if not candidates:
        print("No new account candidates found.")
        return []

    chosen = _llm_select(_rank(candidates), posts, limit)
    for candidate in chosen:
        print(f"@{candidate.username}\t{candidate.evidence()}")

    if add:
        added = sum(accounts.add("instagram", candidate.username) for candidate in chosen)
        logger.info("Added %d discovered Instagram account(s) to inputs.json", added)
    else:
        print("\nPreview only. Run `yuno discover --add` to add these accounts.")
    return chosen
