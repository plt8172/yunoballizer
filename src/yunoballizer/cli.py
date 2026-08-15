"""yunoballizer / yuno CLI entry point."""
from __future__ import annotations

import argparse
import base64
import logging
import sys
import zlib

from . import auth, config, expand, fetch, prune, storage
from . import profile as profile_mod
from . import curate as curate_mod
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

    sub = parser.add_subparsers(dest="command", required=True)

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

    sub.add_parser(
        "fetch",
        help="Requires an active session (see `auth login`). Adds saved-post authors to Instagram accounts.txt",
    )

    auth_parser = sub.add_parser("auth", help="Manage saved Instagram login sessions used by fetch")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    login_parser = auth_sub.add_parser(
        "login", help="Import an Instagram session from a logged-in browser and save it"
    )
    login_parser.add_argument(
        "-b", "--browser", default=auth.DEFAULT_BROWSER,
        help=f"Browser to import the Instagram login session's cookies from (default: {auth.DEFAULT_BROWSER}). "
             "Avoids Instagram's automated-login checkpoint by reusing an already-logged-in session. "
             "Ignored with --interactive.",
    )
    login_parser.add_argument(
        "-i", "--interactive", action="store_true",
        help="Open a dedicated browser window to log in fresh, instead of importing the session "
             "already active in --browser. Lets you add another account without switching accounts "
             "in your everyday browser. Requires the 'playwright' extra.",
    )
    login_parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the confirmation prompt and save the detected session immediately",
    )

    status_parser = auth_sub.add_parser(
        "status", help="List saved Instagram sessions and show which one is active"
    )
    status_parser.add_argument(
        "-c", "--check", action="store_true",
        help="Verify each saved session is still logged in (slower: one request per session)",
    )

    switch_parser = auth_sub.add_parser("switch", help="Switch the active Instagram session")
    switch_parser.add_argument("username", help="Instagram username of a previously saved session")

    logout_parser = auth_sub.add_parser(
        "logout", help="Remove a saved Instagram session (defaults to the active one)"
    )
    logout_parser.add_argument(
        "username", nargs="?", default=None,
        help="Instagram username to remove (default: the active session)",
    )

    sub.add_parser("expand", help="No login required. Expands Instagram accounts.txt from downloaded caption mentions")
    sub.add_parser("profile", help="Build/refresh the content profile from downloaded Instagram captions")
    sub.add_parser("curate", help="Curate new posts against the content profile")
    sub.add_parser("all", help="Run download then curate (cron entry point)")

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
        fetch.run()
    elif args.command == "auth":
        if args.auth_command == "login":
            auth.login(browser=args.browser, interactive=args.interactive, assume_yes=args.yes)
        elif args.auth_command == "status":
            auth.status(check=args.check)
        elif args.auth_command == "switch":
            auth.switch(args.username)
        elif args.auth_command == "logout":
            auth.logout(args.username)
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
    elif args.command == "all":
        _run_download()
        if (config.DERIVED_DIR / profile_mod.PROFILE_FILENAME).exists():
            curate_mod.run()


if __name__ == "__main__":
    main(sys.argv[1:])
