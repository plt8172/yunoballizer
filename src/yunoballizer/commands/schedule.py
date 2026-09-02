"""`yuno schedule`: chain discover -> download -> select for a scheduler.

Bare `yuno schedule` runs one pass of the chain -- this is what launchd's
plist actually invokes on each tick, and it's also safe to run by hand.
discover comes first so newly-found accounts get harvested in the same
run; download comes second so select has fresh items to judge. `discover`
needs at least one selected post to seed from and `select --auto` needs a
configured brain profile -- on a fresh setup either can raise SystemExit,
which is logged and skipped rather than aborting the chain.

`set`/`run`/`pause`/`status` manage the launchd job that calls this
repeatedly, and are macOS-only:
- `set` writes the plist (what to run, how often) without starting it.
- `run` starts it (`launchctl load`) and resets the run/download counters.
- `pause` stops it (`launchctl unload`) without deleting the config.
- `status` reports whether launchd currently has it loaded/running and
  the counters accumulated since the last `run`.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config as app_config
from . import discover
from . import download as download_cmd
from . import select as select_mod

logger = logging.getLogger(__name__)

LABEL = "com.yunoballizer.schedule"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SCHEDULE_DATA_DIR = app_config.DATA_DIR / "schedule"
CONFIG_PATH = app_config.CONFIG_DIR / "schedule.json"
STATS_PATH = SCHEDULE_DATA_DIR / "stats.json"
STDOUT_PATH = SCHEDULE_DATA_DIR / "launchd.out.log"
STDERR_PATH = SCHEDULE_DATA_DIR / "launchd.err.log"


def add_subparser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = sub.add_parser(
        "schedule",
        help="Chain discover -> download -> select -- see `schedule set`/`run`/`pause`/`status`",
    )
    parser.add_argument(
        "--download-limit", type=int, default=20,
        help="Passed through to download's --limit (default: 20)",
    )
    parser.add_argument(
        "--discover-limit", type=int, default=10,
        help="Passed through to discover's --limit (default: 10)",
    )
    parser.add_argument(
        "--select-limit", type=int, default=20,
        help="Passed through to select --auto's --limit (default: 20)",
    )

    schedule_sub = parser.add_subparsers(dest="schedule_command")

    set_parser = schedule_sub.add_parser(
        "set", help="Configure the scheduled job (writes the launchd plist; doesn't start it, macOS only)"
    )
    set_parser.add_argument(
        "--interval", type=float, default=4,
        help="Hours between runs (default: 4)",
    )
    set_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )

    run_parser = schedule_sub.add_parser(
        "run", help="Start the configured job (`launchctl load`, macOS only)"
    )
    run_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )

    schedule_sub.add_parser(
        "pause", help="Stop the configured job (`launchctl unload`) without deleting it (macOS only)"
    )
    schedule_sub.add_parser(
        "status", help="Show whether the job is running, and its stats since the last `run`"
    )
    return parser


def run(args: argparse.Namespace) -> None:
    logger.info("schedule: discover --add (limit=%d)", args.discover_limit)
    try:
        discover.run(limit=args.discover_limit, add=True)
    except SystemExit as exc:
        logger.warning("schedule: skipping discover (%s)", exc)

    logger.info("schedule: download (limit=%d)", args.download_limit)
    downloaded = download_cmd.run(argparse.Namespace(
        limit=args.download_limit,
        skip=0,
        platforms=None,
        since=None,
        until=None,
        media_type=None,
        total_limit=None,
        delay=None,
        target=None,
    ))

    logger.info("schedule: select --auto (limit=%d)", args.select_limit)
    try:
        select_mod.run_auto(limit=args.select_limit)
    except SystemExit as exc:
        logger.warning("schedule: skipping select (%s)", exc)

    _record_run(downloaded)


def _chain_description(args: argparse.Namespace) -> str:
    return (
        f"discover --add (limit={args.discover_limit}) -> "
        f"download (limit={args.download_limit}) -> "
        f"select --auto (limit={args.select_limit})"
    )


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_run(downloaded: int) -> None:
    """Only meaningful once `schedule run` has started the job -- a bare
    `yuno schedule` run by hand still updates it, which is fine, since it's
    just a running total of runs/downloads observed, not a launchd-specific
    counter."""
    stats = _read_json(STATS_PATH, {})
    stats["runs"] = stats.get("runs", 0) + 1
    stats["downloaded"] = stats.get("downloaded", 0) + downloaded
    stats.setdefault("started_at", _now())
    stats["last_run_at"] = _now()
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps(stats, indent=2))


def _launchctl_status(label: str) -> dict:
    result = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
    if result.returncode != 0:
        return {"loaded": False, "pid": None, "last_exit_status": None}
    pid_match = re.search(r'"PID"\s*=\s*(\d+);', result.stdout)
    exit_match = re.search(r'"LastExitStatus"\s*=\s*(-?\d+);', result.stdout)
    return {
        "loaded": True,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "last_exit_status": int(exit_match.group(1)) if exit_match else None,
    }


def _plist_xml(*, yuno_path: str, interval_seconds: int, program_args: list[str]) -> str:
    args_xml = "\n".join(f"        <string>{a}</string>" for a in [yuno_path, "schedule", *program_args])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>

    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{STDOUT_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{STDERR_PATH}</string>
</dict>
</plist>
"""


def _require_macos(command: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit(f"`schedule {command}` is macOS-only (it drives launchd).")


def configure(args: argparse.Namespace) -> None:
    """`schedule set`"""
    _require_macos("set")

    # Prefer the "yunoballizer" entry point over "yuno" so the process shows
    # up under its full name in Activity Monitor / `ps` / `launchctl list`.
    yuno_path = (
        shutil.which("yunoballizer") or shutil.which("yuno") or str(Path(sys.argv[0]).resolve())
    )
    program_args = [
        "--download-limit", str(args.download_limit),
        "--discover-limit", str(args.discover_limit),
        "--select-limit", str(args.select_limit),
    ]
    interval_seconds = int(args.interval * 3600)
    plist = _plist_xml(yuno_path=yuno_path, interval_seconds=interval_seconds, program_args=program_args)

    print(f"Every {args.interval:g}h: {_chain_description(args)}")
    print(f"Job: {LABEL} -> {PLIST_PATH}")
    if _launchctl_status(LABEL)["loaded"]:
        print(
            "Note: the job is currently running with its old settings -- "
            "`schedule pause` then `schedule run` to apply this change."
        )
    if not args.yes:
        answer = input("Write this? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)
    CONFIG_PATH.write_text(json.dumps({
        "interval_hours": args.interval,
        "download_limit": args.download_limit,
        "discover_limit": args.discover_limit,
        "select_limit": args.select_limit,
    }, indent=2))
    print(f"Wrote {PLIST_PATH}.")
    print("Run `yuno schedule run` to start it.")


def start(args: argparse.Namespace) -> None:
    """`schedule run`"""
    _require_macos("run")
    if not PLIST_PATH.exists():
        raise SystemExit("Not configured yet. Run `yuno schedule set` first.")

    if _launchctl_status(LABEL)["loaded"]:
        print(f"{LABEL} is already running.")
        return

    settings = _read_json(CONFIG_PATH, {})
    print(f"Starting {LABEL} (every {settings.get('interval_hours', '?')}h) from {PLIST_PATH}")
    if not args.yes:
        answer = input("Load it now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps({
        "runs": 0, "downloaded": 0, "started_at": _now(), "last_run_at": None,
    }, indent=2))
    print(f"Started. Logs: {SCHEDULE_DATA_DIR}/launchd.{{out,err}}.log")


def pause(args: argparse.Namespace) -> None:
    """`schedule pause`"""
    _require_macos("pause")
    if not PLIST_PATH.exists():
        raise SystemExit("Not configured. Run `yuno schedule set` first.")

    if not _launchctl_status(LABEL)["loaded"]:
        print(f"{LABEL} is not running.")
        return

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=True)
    print(f"Paused {LABEL}. Run `yuno schedule run` to resume.")


def status(args: argparse.Namespace) -> None:
    """`schedule status`"""
    if not PLIST_PATH.exists():
        print("Not configured. Run `yuno schedule set` first.")
        return

    settings = _read_json(CONFIG_PATH, {})
    print(f"Configured: every {settings.get('interval_hours', '?')}h -> {PLIST_PATH}")

    if sys.platform == "darwin":
        launchctl = _launchctl_status(LABEL)
        if launchctl["loaded"]:
            state = f"running (pid {launchctl['pid']})" if launchctl["pid"] else "loaded, waiting for next tick"
            print(f"Status: {state}")
        else:
            print("Status: paused / not loaded")
        if launchctl["last_exit_status"] is not None:
            print(f"Last run exit status: {launchctl['last_exit_status']}")
    else:
        print("Status: unknown (launchctl is macOS-only)")

    stats = _read_json(STATS_PATH, {})
    if stats:
        print(
            f"Since {stats.get('started_at', '?')}: "
            f"{stats.get('runs', 0)} run(s), {stats.get('downloaded', 0)} item(s) downloaded"
        )
        if stats.get("last_run_at"):
            print(f"Last run: {stats['last_run_at']}")
    else:
        print("No runs recorded yet.")
