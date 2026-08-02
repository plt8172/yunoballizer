"""yunoballizer / yuno CLI entry point."""
from __future__ import annotations

import argparse
import base64
import logging
import sys
import zlib

from . import config, discover, prune
from . import profile as profile_mod
from . import curate as curate_mod
from .downloaders import instagram, tiktok, youtube
from .downloaders import urls as urls_mod

logger = logging.getLogger("yunoballizer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yunoballizer",
        description="Personal automation tool for collecting content from Instagram, YouTube Shorts, and TikTok",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    sub = parser.add_subparsers(dest="command", required=True)

    download_parser = sub.add_parser("download", help="No login required. Anonymous harvesting of accounts + urls.txt")
    download_parser.add_argument(
        "-l", "--limit", type=int, default=20,
        help="Max posts to harvest per account (default: 20)",
    )
    download_parser.add_argument(
        "target", nargs="?", default=None,
        help="Harvest a single target across instagram/youtube/tiktok instead of the configured lists. "
             "Must start with '@' for an account, e.g. '@nasa' (hashtag support may come later)",
    )

    sub.add_parser("discover", help="Requires login. Harvests hashtags + saved posts, auto-discovers accounts (manual/low-frequency)")
    sub.add_parser("profile", help="Build/refresh the taste profile from saved posts")
    sub.add_parser("curate", help="Curate new posts against the taste profile")
    sub.add_parser("all", help="Run download then curate (cron entry point)")

    prune_parser = sub.add_parser(
        "prune",
        help="Remove this app's config/data/log directories (does not remove the installed package)",
    )
    prune_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    return parser


def _run_download(limit: int = 20, accounts: list[str] | None = None) -> None:
    instagram.harvest(limit=limit, accounts=accounts)
    youtube.harvest(limit=limit, accounts=accounts)
    tiktok.harvest(limit=limit, accounts=accounts)
    if accounts is None:
        urls_mod.harvest()


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv == ["ball"]:
        from . import templates
        print()
        print(zlib.decompress(base64.b64decode(templates._INDEX)).decode())
        print()
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    if args.command == "prune":
        prune.run(assume_yes=args.yes)
        return

    config.ensure_config()

    if args.command == "discover":
        discover.run()
    elif args.command == "download":
        accounts = None
        if args.target:
            if not args.target.startswith("@"):
                raise SystemExit(f"Invalid target '{args.target}': accounts must start with '@' (e.g. '@nasa')")
            accounts = [args.target[1:]]
        _run_download(limit=args.limit, accounts=accounts)
    elif args.command == "profile":
        profile_mod.build()
    elif args.command == "curate":
        curate_mod.run()
    elif args.command == "all":
        _run_download()
        if (config.CONFIG_DIR / profile_mod.PROFILE_FILENAME).exists():
            curate_mod.run()


if __name__ == "__main__":
    main(sys.argv[1:])
