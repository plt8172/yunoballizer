"""yunoballizer / yuno CLI entry point."""
from __future__ import annotations

import argparse
import base64
import logging
import sys
import zlib
from pathlib import Path

from . import config, expand, fetch, prune, storage
from . import profile as profile_mod
from . import curate as curate_mod
from . import select as select_mod
from .downloaders import instagram, tiktok, youtube
from .downloaders import urls as urls_mod

logger = logging.getLogger("yunoballizer")


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yunoballizer",
        description="Personal automation tool for collecting content from Instagram, YouTube Shorts, and TikTok",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    sub = parser.add_subparsers(
        dest="command", required=True,
        metavar="{download,fetch,expand,profile,curate,select,export,all,prune}",
    )

    download_parser = sub.add_parser("download", help="No login required. Anonymous harvesting of accounts + urls.txt")
    download_parser.add_argument(
        "-l", "--limit", type=int, default=20,
        help="Max posts to harvest per account (default: 20)",
    )
    download_parser.add_argument(
        "-s", "--skip", type=_non_negative_int, default=0,
        help="Skip the newest N posts per account before harvesting (default: 0)",
    )
    download_parser.add_argument(
        "target", nargs="?", default=None,
        help="Harvest a single target across instagram/youtube/tiktok instead of the configured lists. "
             "Must start with '@' for an account, e.g. '@nasa' (hashtag support may come later)",
    )

    fetch_parser = sub.add_parser("fetch", help="Requires login. Adds saved-post authors to Instagram accounts.txt")
    fetch_parser.add_argument(
        "-b", "--browser", default=fetch.DEFAULT_BROWSER,
        help=f"Browser to import the Instagram login session's cookies from (default: {fetch.DEFAULT_BROWSER}). "
             "Avoids Instagram's automated-login checkpoint by reusing an already-logged-in session.",
    )
    sub.add_parser("expand", help="No login required. Expands Instagram accounts.txt from downloaded caption mentions")
    sub.add_parser("profile", help="Build/refresh the content profile from downloaded Instagram captions")
    sub.add_parser("curate", help="Curate new posts against the content profile")

    sub.add_parser(
        "select",
        help="Browse review/ in fzf (Tab to mark, Enter to confirm, o to open in your OS's default viewer/player)",
    )
    sub.add_parser("export", help="Copy/hardlink selected media into selected/")

    sub.add_parser("all", help="Run download then curate (cron entry point)")

    # Internal plumbing: fzf's --preview and 'o' keybind shell out to these
    # rather than an inline shell script, so `select.pick()` never needs to
    # know which shell fzf happens to invoke on a given platform.
    preview_parser = sub.add_parser("_preview")
    preview_parser.add_argument("path")
    open_parser = sub.add_parser("_open")
    open_parser.add_argument("path")

    prune_parser = sub.add_parser(
        "prune",
        help="Remove this app's config/data/log directories (does not remove the installed package)",
    )
    prune_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    return parser


def _run_download(
    limit: int = 20,
    skip: int = 0,
    accounts: list[str] | None = None,
) -> None:
    instagram.harvest(limit=limit, skip=skip, accounts=accounts)
    youtube.harvest(limit=limit, skip=skip, accounts=accounts)
    tiktok.harvest(limit=limit, skip=skip, accounts=accounts)
    if accounts is None:
        urls_mod.harvest()
    added = storage.refresh_review()
    logger.info("New items added to review/: %d", added)


def _run_expand() -> None:
    added_caption = expand.scan_caption_mentions()
    logger.info("New Instagram accounts added from caption mentions: %d", added_caption)


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

    if args.command == "fetch":
        fetch.run(browser=args.browser)
    elif args.command == "expand":
        _run_expand()
    elif args.command == "download":
        accounts = None
        if args.target:
            if not args.target.startswith("@"):
                raise SystemExit(f"Invalid target '{args.target}': accounts must start with '@' (e.g. '@nasa')")
            accounts = [args.target[1:]]
        _run_download(limit=args.limit, skip=args.skip, accounts=accounts)
    elif args.command == "profile":
        profile_mod.build()
    elif args.command == "curate":
        curate_mod.run()
    elif args.command == "select":
        select_mod.run_select()
    elif args.command == "export":
        select_mod.run_export()
    elif args.command == "_preview":
        select_mod.render_preview(Path(args.path))
    elif args.command == "_open":
        select_mod.open_native(Path(args.path))
    elif args.command == "all":
        _run_download()
        if (config.DERIVED_DIR / profile_mod.PROFILE_FILENAME).exists():
            curate_mod.run()


if __name__ == "__main__":
    main(sys.argv[1:])
