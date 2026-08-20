"""`yuno download`: anonymous harvesting of inputs.json, or a single ad-hoc target.

Split out of cli.py once this grew past a couple of argparse options: this
module owns the download subparser's flags, the multi-account/platform
harvest orchestration (_run_download), and routing a single positional
target -- an "@account" or a direct post/video URL -- to the right
downloader (instagram/youtube/tiktok account harvesting, Instaloader for a
lone Instagram URL, yt-dlp for anything else).
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from .. import storage
from ..downloaders import instagram, tiktok, youtube
from ..downloaders import urls as urls_mod
from ..downloaders.budget import TotalBudget

logger = logging.getLogger(__name__)

PLATFORMS = ("instagram", "youtube", "tiktok")


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}, expected YYYY-MM-DD")


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def add_subparser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    download_parser = sub.add_parser(
        "download", help="No login required. Anonymous harvesting of inputs.json"
    )
    download_parser.add_argument(
        "-l", "--limit", type=int, default=20,
        help="Max posts to harvest per account (default: 20)",
    )
    download_parser.add_argument(
        "-s", "--skip", type=_non_negative_int, default=0,
        help="Skip the newest N posts per account before harvesting (default: 0)",
    )
    download_parser.add_argument(
        "-p", "--platform", action="append", choices=PLATFORMS, dest="platforms", default=None,
        help="Restrict harvesting to one platform; repeat to allow more than one "
             "(default: all configured platforms). Also excludes configured URLs for that run, "
             "since it isn't tied to a single platform",
    )
    download_parser.add_argument(
        "--since", type=_date, default=None,
        help="Only harvest posts published on or after this date (YYYY-MM-DD)",
    )
    download_parser.add_argument(
        "--until", type=_date, default=None,
        help="Only harvest posts published on or before this date (YYYY-MM-DD)",
    )
    download_parser.add_argument(
        "-t", "--type", choices=["photo", "video"], default=None, dest="media_type",
        help="Only harvest photos or videos. YouTube Shorts and TikTok posts are "
             "always video, so --type photo skips those platforms entirely",
    )
    download_parser.add_argument(
        "--total-limit", type=_non_negative_int, default=None,
        help="Cap the total number of posts requested across every account and "
             "platform combined in this run, on top of the per-account --limit "
             "(default: unlimited)",
    )
    download_parser.add_argument(
        "--delay", type=_non_negative_int, default=None,
        help="Seconds to wait between accounts, overriding each platform's own "
             "default (Instagram: 20s, TikTok: 15s, YouTube: 0s)",
    )
    download_parser.add_argument(
        "target", nargs="?", default=None,
        help="Harvest a single target instead of the configured lists: an account "
             "across instagram/youtube/tiktok (must start with '@', e.g. '@nasa'), "
             "or a direct post/video URL (Instagram/YouTube/TikTok/etc.) to download just that one item",
    )
    return download_parser


def _run_download(
    limit: int = 20,
    skip: int = 0,
    accounts: list[str] | None = None,
    platforms: list[str] | None = None,
    since: date | None = None,
    until: date | None = None,
    media_type: str | None = None,
    total_limit: int | None = None,
    delay: int | None = None,
) -> None:
    selected = set(platforms) if platforms else set(PLATFORMS)
    budget = TotalBudget(total_limit) if total_limit is not None else None
    # Each harvest() below refreshes review/ incrementally as it goes (per
    # account, per post) rather than waiting for the whole run to finish --
    # so a single refresh_review() call here at the end would only ever see
    # 0 left to add. Share one ReviewProgress across every platform instead
    # and read its running total.
    progress = storage.ReviewProgress()

    extra: dict = {"progress": progress}
    if since is not None:
        extra["since"] = since
    if until is not None:
        extra["until"] = until
    if media_type is not None:
        extra["media_type"] = media_type
    if budget is not None:
        extra["budget"] = budget
    if delay is not None:
        extra["sleep_seconds"] = delay

    if "instagram" in selected:
        instagram.harvest(limit=limit, skip=skip, accounts=accounts, **extra)
    if "youtube" in selected:
        youtube.harvest(limit=limit, skip=skip, accounts=accounts, **extra)
    if "tiktok" in selected:
        tiktok.harvest(limit=limit, skip=skip, accounts=accounts, **extra)
    if accounts is None and platforms is None:
        urls_mod.harvest(progress=progress, budget=budget)
    logger.info("New items added to review/: %d", progress.total)


def _run_target_url(url: str) -> None:
    """Download a single ad-hoc post/video URL passed directly as `yuno download`'s target.

    Uses the same URL router as configured URLs: Instagram links go through
    Instaloader and everything else through yt-dlp.
    """
    progress = storage.ReviewProgress()
    urls_mod.download_urls([url], progress=progress)
    logger.info("New items added to review/: %d", progress.total)


def run(args: argparse.Namespace) -> None:
    if args.since is not None and args.until is not None and args.since > args.until:
        raise SystemExit(f"--since ({args.since}) is after --until ({args.until})")

    if args.target and _is_url(args.target):
        _run_target_url(args.target)
        return

    accounts = None
    if args.target:
        if not args.target.startswith("@"):
            raise SystemExit(
                f"Invalid target '{args.target}': accounts must start with '@' (e.g. '@nasa'), "
                "or pass a full http(s):// URL to download a single post/video"
            )
        accounts = [args.target[1:]]

    _run_download(
        limit=args.limit,
        skip=args.skip,
        accounts=accounts,
        platforms=args.platforms,
        since=args.since,
        until=args.until,
        media_type=args.media_type,
        total_limit=args.total_limit,
        delay=args.delay,
    )
