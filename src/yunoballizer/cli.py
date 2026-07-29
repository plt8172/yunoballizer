"""yunoballizer / yuno CLI entry point."""
from __future__ import annotations

import argparse
import logging
import sys

from . import config, discover, instagram, mentions, tiktok, uninstall
from . import urls as urls_mod
from . import youtube
from . import profile as profile_mod
from . import curate as curate_mod

logger = logging.getLogger("yunoballizer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yunoballizer",
        description="Personal automation tool for collecting content from Instagram, YouTube Shorts, and TikTok",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="Requires login. Harvests hashtags + saved posts, auto-discovers accounts (manual/low-frequency)")
    sub.add_parser("download", help="No login required. Anonymous harvesting + caption-mention account expansion")
    sub.add_parser("profile", help="Build/refresh the taste profile from saved posts")
    sub.add_parser("curate", help="Curate new posts against the taste profile")
    sub.add_parser("all", help="Run download then curate (cron entry point)")

    uninstall_parser = sub.add_parser(
        "uninstall",
        help="Remove this app's config/data/log directories (does not remove the installed package)",
    )
    uninstall_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    return parser


def _run_download() -> None:
    instagram.harvest()
    added = mentions.scan_and_append()
    logger.info("New accounts added via caption mentions: %d", added)
    urls_mod.harvest()
    youtube.harvest()
    tiktok.harvest()


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    if args.command == "uninstall":
        uninstall.run(assume_yes=args.yes)
        return

    config.ensure_config()

    if args.command == "discover":
        discover.run()
    elif args.command == "download":
        _run_download()
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
