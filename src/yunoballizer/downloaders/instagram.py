"""Anonymous (no-login) Instagram account harvesting.

Uses the instaloader library directly instead of shelling out to its CLI:
Instaloader.download_profiles() honors max_count for plain profile targets,
but the instaloader CLI never forwards --count to that codepath (it's only
wired up for #hashtag/:saved/:feed targets there), so the CLI has no way to
cap posts per account.

Each post is saved to its own sources/instagram/<account>/<shortcode>/
directory (dedup checks that directory directly), then its files -- named
"post"/"post_<n>" by filename_pattern -- are renamed to the canonical
image_NN/video/caption/metadata scheme. fast_update is disabled because it
keys off Instaloader's own (pre-rename) filenames, which the
directory-existence check already makes redundant.

The per-post shortcode is threaded through filename_pattern ("{shortcode}/post"),
not dirname_pattern: Instaloader also plain-`str.format()`s dirname_pattern
with only `profile`/`target` in a couple of places outside of downloading an
individual post (profile-level metadata, the resume-file path), which would
raise KeyError if dirname_pattern referenced `{shortcode}`. filename_pattern
is never touched by those call sites, and Instaloader creates whatever
subdirectories a "/" in it implies, so this gets the same per-post directory
without going near that landmine.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path

import instaloader

from .. import config, storage
from .budget import TotalBudget

logger = logging.getLogger("yunoballizer.instagram")

_URL_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def is_instagram_url(url: str) -> bool:
    return _URL_SHORTCODE_RE.search(url) is not None


def _new_loader(out_dir: Path) -> instaloader.Instaloader:
    return instaloader.Instaloader(
        dirname_pattern=str(out_dir / "{target}"),
        filename_pattern=f"{{shortcode}}/{storage.INSTAGRAM_FILENAME_PATTERN}",
        quiet=True,
        download_comments=False,
        download_video_thumbnails=False,
    )


def _remove_profile_metadata_json(
    account_dir: Path, profile: instaloader.Profile, loader: instaloader.Instaloader
) -> None:
    # Instaloader.download_profiles() unconditionally writes a
    # "<username>_<userid>.json[.xz]" profile-level metadata file whenever
    # save_metadata is on -- and save_metadata can't just be turned off,
    # since it's the same flag that produces the per-post metadata this
    # project relies on. Delete the stray profile-level file it leaves in
    # the account root.
    ext = ".json.xz" if loader.compress_json else ".json"
    stray = account_dir / f"{profile.username}_{profile.userid}{ext}"
    stray.unlink(missing_ok=True)


def harvest(
    sleep_seconds: int = 20,
    limit: int = 20,
    accounts: list[str] | None = None,
    skip: int = 0,
    since: date | None = None,
    until: date | None = None,
    media_type: str | None = None,
    budget: TotalBudget | None = None,
) -> None:
    if accounts is None:
        accounts_file = config.CONFIG_DIR / "instagram" / "accounts.txt"
        accounts = config.read_lines(accounts_file)
        if not accounts:
            logger.info("%s is empty, skipping", accounts_file)
            return

    out_dir = config.SOURCES_DIR / "instagram"
    out_dir.mkdir(parents=True, exist_ok=True)

    loader = _new_loader(out_dir)

    for account in accounts:
        if budget is not None and budget.exhausted:
            logger.info("Total download limit reached; stopping.")
            break
        account_limit = budget.take(limit) if budget is not None else limit
        if account_limit <= 0:
            continue

        logger.info("[account] checking %s...", account)
        account_dir = out_dir / account
        try:
            profile = instaloader.Profile.from_username(loader.context, account)
            account_dir = out_dir / profile.username
            remaining_to_skip = skip

            def include_post(post: object) -> bool:
                nonlocal remaining_to_skip
                if remaining_to_skip:
                    remaining_to_skip -= 1
                    return False
                if since is not None and post.date_utc.date() < since:
                    return False
                if until is not None and post.date_utc.date() > until:
                    return False
                if media_type == "photo" and post.is_video:
                    return False
                if media_type == "video" and not post.is_video:
                    return False
                post_dir = account_dir / post.shortcode
                if not post_dir.is_dir():
                    return True
                # Compare against the post's own reported media count, not
                # just "any file present": a post interrupted mid-download
                # (process killed, network drop) can leave a non-empty but
                # incomplete carousel dir, which should be retried rather
                # than skipped forever.
                existing_media = sum(
                    1 for p in post_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in storage.MEDIA_EXTS
                )
                return existing_media < post.mediacount

            loader.download_profiles(
                {profile},
                profile_pic=False,
                fast_update=False,
                max_count=skip + account_limit,
                post_filter=include_post,
            )
            _remove_profile_metadata_json(account_dir, profile, loader)
        except instaloader.InstaloaderException as e:
            logger.error("Failed to harvest %s: %s", account, e)
        finally:
            # Instaloader has no per-post-finished callback, so this is the
            # finest granularity available here: review/ picks up a whole
            # account's newly downloaded posts as soon as that account is
            # done, rather than waiting for every account across every
            # platform to finish before anything is browsable.
            storage.organize_instagram_account(account_dir)
            storage.refresh_review()
        time.sleep(sleep_seconds)


def harvest_urls(urls: list[str]) -> None:
    """Download individual Instagram post URLs (from urls.txt) directly via Instaloader.

    Routed here instead of through yt-dlp: yt-dlp's Instagram extractor has
    no support for photo posts at all (nothing downloads), and its video
    extraction has been unreliable since Instagram tightened anti-scraping
    (files download but fail to play). Instaloader -- already used for
    account harvesting -- has neither problem, since it talks to Instagram's
    own post-info endpoints instead of scraping/guessing a media URL.
    """
    out_dir = config.SOURCES_DIR / "instagram"
    out_dir.mkdir(parents=True, exist_ok=True)
    loader = _new_loader(out_dir)

    for url in urls:
        match = _URL_SHORTCODE_RE.search(url)
        if match is None:
            logger.error("Could not parse an Instagram shortcode from %s", url)
            continue
        shortcode = match.group(1)

        try:
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
        except instaloader.InstaloaderException as e:
            logger.error("Failed to fetch %s: %s", url, e)
            continue

        account_dir = out_dir / post.owner_username
        post_dir = account_dir / post.shortcode
        if post_dir.is_dir():
            existing_media = sum(
                1 for p in post_dir.iterdir()
                if p.is_file() and p.suffix.lower() in storage.MEDIA_EXTS
            )
            if existing_media >= post.mediacount:
                continue

        try:
            loader.download_post(post, target=post.owner_username)
        except instaloader.InstaloaderException as e:
            logger.error("Failed to download %s: %s", url, e)
        finally:
            storage.organize_instagram_account(account_dir)
            storage.refresh_review()
