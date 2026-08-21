"""yunoballizer / yuno CLI entry point."""
from __future__ import annotations

import argparse
import base64
import logging
import sys
import zlib

from . import config, llm, storage
from .commands import accounts as accounts_mod
from .commands import urls as urls_mod
from .commands import auth, discover, download as download_cmd, fetch, prune, schedule
from .commands import brain as brain_mod
from .commands import larp as larp_mod
from .commands import select as select_mod

logger = logging.getLogger("yunoballizer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yunoballizer",
        description="Personal automation tool for collecting content from Instagram, YouTube Shorts, and TikTok",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    sub = parser.add_subparsers(dest="command", required=True)

    download_cmd.add_subparser(sub)

    fetch_parser = sub.add_parser(
        "fetch",
        help="Requires an active session (see `auth login`). Adds Instagram accounts to inputs.json",
    )
    fetch_parser.add_argument(
        "-l", "--limit", type=int, default=None,
        help="Max items to read per selected source (default: no limit). With more than one "
             "--source, the combined result can be up to N times this -- see --total-limit",
    )
    fetch_parser.add_argument(
        "--total-limit", type=int, default=None,
        help="Max accounts across all selected sources combined, applied after merging them "
             "(default: no limit). Not an alias for --limit: with a single source they agree, "
             "but only --total-limit stays a true total once more than one --source is given",
    )
    fetch_parser.add_argument(
        "--sync", action="store_true",
        help="Make the Instagram input list match exactly what's found this run -- removes any account not "
             "in the selected source(s), not just adds new ones",
    )
    fetch_parser.add_argument(
        "--source", nargs="+", default=["saved"], metavar="SOURCE",
        help=f"Where to pull accounts from (default: saved). Multiple allowed, e.g. "
             f"'--source saved following'. Supported: {', '.join(fetch.SOURCES)}. "
             f"NOT available -- no Instagram API exposes them, official or not -- "
             f"{', '.join(fetch._UNSUPPORTED_SOURCES)}",
    )

    auth_parser = sub.add_parser("auth", help="Manage saved Instagram login sessions used by fetch")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    login_parser = auth_sub.add_parser(
        "login", help="Log in to Instagram (opens a browser window) and save the session"
    )
    login_parser.add_argument(
        "-b", "--browser", default=auth.DEFAULT_BROWSER,
        help=f"Browser to use (default: {auth.DEFAULT_BROWSER}). For 'chrome' or 'edge', opens a "
             "dedicated login window driving that already-installed browser directly (no download "
             "needed) -- the better way to add another account, since it never touches an everyday "
             "browser's own session. For any other value, or if that window can't be opened, falls "
             "back to importing the session already active in that browser instead.",
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
    switch_parser.add_argument(
        "username", nargs="?", default=None,
        help="Instagram username of a previously saved session (default: cycle to the next saved session)",
    )

    logout_parser = auth_sub.add_parser(
        "logout", help="Remove one or more saved Instagram sessions (defaults to the active one)"
    )
    logout_parser.add_argument(
        "username", nargs="*",
        help="Instagram username(s) to remove (default: just the active session)",
    )

    accounts_parser = sub.add_parser("accounts", help="View or edit per-platform account IDs in inputs.json")
    accounts_sub = accounts_parser.add_subparsers(dest="accounts_command", required=True)

    accounts_list_parser = accounts_sub.add_parser("list", help="List monitored accounts")
    accounts_list_parser.add_argument(
        "platform", nargs="?", choices=accounts_mod.PLATFORMS, default=None,
        help="Limit to one platform (default: all)",
    )

    accounts_add_parser = accounts_sub.add_parser("add", help="Add an account to monitor")
    accounts_add_parser.add_argument("platform", choices=accounts_mod.PLATFORMS)
    accounts_add_parser.add_argument("username")

    accounts_remove_parser = accounts_sub.add_parser("remove", help="Stop monitoring an account")
    accounts_remove_parser.add_argument("platform", choices=accounts_mod.PLATFORMS)
    accounts_remove_parser.add_argument("username")

    urls_parser = sub.add_parser("urls", help="View or edit persistent URLs in inputs.json")
    urls_sub = urls_parser.add_subparsers(dest="urls_command", required=True)
    urls_sub.add_parser("list", help="List saved URLs")
    urls_add_parser = urls_sub.add_parser("add", help="Add a URL to future downloads")
    urls_add_parser.add_argument("url")
    urls_remove_parser = urls_sub.add_parser("remove", help="Remove a URL from future downloads")
    urls_remove_parser.add_argument("url")

    discover_parser = sub.add_parser(
        "discover", help="Find new Instagram accounts from selected posts, similar accounts, and mentions"
    )
    discover_parser.add_argument(
        "-l", "--limit", type=int, default=10,
        help="Maximum account candidates to show (default: 10)",
    )
    discover_parser.add_argument(
        "--add", action="store_true",
        help="Add the shown candidates to inputs.json (default: preview only)",
    )

    select_parser = sub.add_parser(
        "select",
        help="Select downloads manually, or automatically with --auto",
    )
    select_parser.add_argument(
        "--auto",
        action="store_true",
        help="Use the LLM to select new downloads from manual selections and rejections",
    )
    select_parser.add_argument(
        "-l", "--limit", type=int, default=None,
        help="Maximum new posts to judge in --auto mode (default: 20)",
    )
    sub.add_parser("export", help="Copy/hardlink selected media into selected/")

    schedule.add_subparser(sub)

    brain_parser = sub.add_parser(
        "brain", help="Configure named AI provider profiles used by select, discover, and larp"
    )
    brain_sub = brain_parser.add_subparsers(dest="brain_command")
    brain_config_parser = brain_sub.add_parser(
        "config", help="Add or update a named profile (interactive) and make it active"
    )
    brain_config_parser.add_argument(
        "name", nargs="?", default="default", help="Profile name (default: 'default')"
    )
    brain_sub.add_parser("list", help="List saved profiles, marking the active one")
    brain_switch_parser = brain_sub.add_parser("switch", help="Switch the active profile")
    brain_switch_parser.add_argument(
        "name", nargs="?", default=None,
        help="Profile to switch to (default: cycle to the next one)",
    )
    brain_remove_parser = brain_sub.add_parser("remove", help="Delete a saved profile")
    brain_remove_parser.add_argument("name", help="Profile name to delete")

    larp_parser = sub.add_parser(
        "larp",
        help="Generate comment/caption text from per-style saved templates via Groq's "
             "free-tier LLM API",
    )
    larp_parser.add_argument(
        "-s", "--style", default=None,
        help="Which saved style to draw from (see `yuno larp list`). Required if more "
             "than one style is saved, to avoid mixing styles together",
    )
    larp_parser.add_argument(
        "-n", "--count", type=int, default=1, help="Number of texts to generate (default: 1)"
    )
    larp_parser.add_argument(
        "--model", default=None,
        help="Model name for the target API. Defaults to $YUNOBALLIZER_MODEL, or "
             "'llama-3.3-70b-versatile' if unset",
    )
    larp_parser.add_argument(
        "--api-base", default=None,
        help="OpenAI-compatible chat completions endpoint URL. Defaults to "
             "$YUNOBALLIZER_API_BASE, or Groq's API if unset. Any provider with the "
             "same request/response shape works (OpenRouter, Together, a local "
             "vLLM/LM Studio server, etc.) -- also pass --model and set "
             "YUNOBALLIZER_API_KEY to that provider's key",
    )
    larp_parser.add_argument(
        "--timeout", type=int, default=30,
        help="Request timeout in seconds (default: 30)",
    )
    larp_parser.add_argument(
        "--max-tokens", type=int, default=llm.DEFAULT_MAX_TOKENS,
        help=f"Max output tokens per generated text (default: {llm.DEFAULT_MAX_TOKENS}). "
             "Raise this if a model cuts off before finishing -- reasoning/thinking "
             "models especially can spend most of the budget on hidden reasoning "
             "before producing visible output",
    )
    larp_parser.add_argument(
        "-l", "--language", default=None,
        help="Language to generate in (e.g. 'English', 'Korean'), overriding the "
             "examples' own language while keeping their style. Default: whatever "
             "language the style's examples are already in",
    )
    larp_sub = larp_parser.add_subparsers(dest="larp_command")
    larp_add_parser = larp_sub.add_parser(
        "add", help="Save a new template under a style (also doable via `yuno select`'s 'c' key)"
    )
    larp_add_parser.add_argument("style", help="Style name (alias) to save the template under, e.g. 'casual'")
    larp_add_parser.add_argument("text", help="Template text to save")
    larp_list_parser = larp_sub.add_parser(
        "list",
        help="List saved styles, or browse a style's templates one at a time "
             "(arrow keys) if a style is given",
    )
    larp_list_parser.add_argument("style", nargs="?", default=None, help="Style name to browse templates for")
    larp_remove_parser = larp_sub.add_parser(
        "remove", help="Remove a saved template by index (see `yuno larp list <style>`)"
    )
    larp_remove_parser.add_argument("style", help="Style name the template belongs to")
    larp_remove_parser.add_argument("index", type=int)
    larp_rename_parser = larp_sub.add_parser("rename", help="Rename a style (its alias)")
    larp_rename_parser.add_argument("old", help="Current style name")
    larp_rename_parser.add_argument("new", help="New style name")
    larp_delete_parser = larp_sub.add_parser("delete", help="Delete a style and all of its templates")
    larp_delete_parser.add_argument("style", help="Style name to delete")

    prune_parser = sub.add_parser(
        "prune",
        help="Remove this app's config/data/log directories (does not remove the installed package)",
    )
    prune_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    return parser


def _run_larp(args: argparse.Namespace) -> None:
    if args.larp_command == "add":
        try:
            larp_mod.add_template(args.style, args.text)
        except ValueError as exc:
            raise SystemExit(str(exc))
        logger.info("Template saved under style %r.", args.style)
    elif args.larp_command == "list":
        if args.style is None:
            styles = larp_mod.list_styles()
            if not styles:
                print("No saved styles.")
            for style in styles:
                count = len(larp_mod.read_templates(style))
                print(f"{style} ({count} template{'s' if count != 1 else ''})")
        else:
            larp_mod.browse(args.style)
    elif args.larp_command == "remove":
        try:
            removed = larp_mod.remove_template(args.style, args.index)
        except IndexError as exc:
            raise SystemExit(str(exc))
        logger.info("Removed template [%d] from style %r: %s", args.index, args.style, removed)
    elif args.larp_command == "rename":
        larp_mod.rename_style(args.old, args.new)
        logger.info("Renamed style %r to %r.", args.old, args.new)
    elif args.larp_command == "delete":
        larp_mod.delete_style(args.style)
        logger.info("Deleted style %r.", args.style)
    else:
        texts = larp_mod.generate(
            style=args.style,
            count=args.count,
            model=args.model,
            api_base=args.api_base,
            language=args.language,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
        )
        for text in texts:
            print(text)


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv == ["ball"]:
        from .commands import _INDEX
        print()
        print(zlib.decompress(base64.b64decode(_INDEX)).decode())
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
    config.load_env_file()

    if args.command == "fetch":
        fetch.run(limit=args.limit, sync=args.sync, sources=args.source, total_limit=args.total_limit)
    elif args.command == "auth":
        if args.auth_command == "login":
            auth.login(browser=args.browser, assume_yes=args.yes)
        elif args.auth_command == "status":
            auth.status(check=args.check)
        elif args.auth_command == "switch":
            auth.switch(args.username)
        elif args.auth_command == "logout":
            auth.logout(args.username)
    elif args.command == "accounts":
        if args.accounts_command == "list":
            for platform, names in accounts_mod.list_accounts(args.platform).items():
                print(f"{platform} ({len(names)}):")
                for name in names:
                    print(f"  {name}")
        elif args.accounts_command == "add":
            added = accounts_mod.add(args.platform, args.username)
            username = args.username.strip().lstrip("@").lower()
            print(f"{'Added' if added else 'Already present:'} @{username} ({args.platform})")
        elif args.accounts_command == "remove":
            username = args.username.strip().lstrip("@").lower()
            removed = accounts_mod.remove(args.platform, args.username)
            print(f"{'Removed' if removed else 'Not found:'} @{username} ({args.platform})")
    elif args.command == "urls":
        if args.urls_command == "list":
            urls = urls_mod.list_urls()
            print(f"urls ({len(urls)}):")
            for url in urls:
                print(f"  {url}")
        elif args.urls_command == "add":
            added = urls_mod.add(args.url)
            url = args.url.strip()
            print(f"{'Added' if added else 'Already present:'} {url}")
        elif args.urls_command == "remove":
            removed = urls_mod.remove(args.url)
            url = args.url.strip()
            print(f"{'Removed' if removed else 'Not found:'} {url}")
    elif args.command == "download":
        download_cmd.run(args)
    elif args.command == "discover":
        if args.limit < 1:
            raise SystemExit("--limit must be at least 1")
        discover.run(limit=args.limit, add=args.add)
    elif args.command == "select":
        if args.auto:
            limit = 20 if args.limit is None else args.limit
            if limit < 1:
                raise SystemExit("--limit must be at least 1")
            select_mod.run_auto(limit=limit)
        else:
            if args.limit is not None:
                raise SystemExit("--limit requires --auto")
            select_mod.run_select()
    elif args.command == "export":
        select_mod.run_export()
    elif args.command == "schedule":
        schedule_command = getattr(args, "schedule_command", None)
        if schedule_command == "set":
            schedule.configure(args)
        elif schedule_command == "run":
            schedule.start(args)
        elif schedule_command == "pause":
            schedule.pause(args)
        elif schedule_command == "status":
            schedule.status(args)
        else:
            schedule.run(args)
    elif args.command == "larp":
        _run_larp(args)
    elif args.command == "brain":
        if args.brain_command is None:
            print(brain_mod.describe_active())
        elif args.brain_command == "config":
            brain_mod.configure(args.name)
        elif args.brain_command == "list":
            names = brain_mod.saved_profiles()
            if not names:
                print("No saved brain profiles. Run `yuno brain config <name>` to add one.")
            active = brain_mod.active_profile_name()
            for name in names:
                marker = "*" if name == active else " "
                print(f"  {marker} {brain_mod.describe(name)}")
        elif args.brain_command == "switch":
            name = brain_mod.switch(args.name)
            print(f"Switched active brain profile to {name!r}.")
        elif args.brain_command == "remove":
            brain_mod.remove_profile(args.name)
            print(f"Removed brain profile {args.name!r}.")


if __name__ == "__main__":
    main(sys.argv[1:])
