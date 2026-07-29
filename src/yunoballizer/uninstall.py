"""Removes config, data, and log directories created by this app.

This does NOT remove the installed Python package itself — that's the job
of your package manager (pip uninstall / pipx uninstall / etc.). This only
cleans up the files this app creates on disk (config, collected content,
logs) that a package manager has no knowledge of and won't remove for you.
"""
from __future__ import annotations

import logging
import shutil

from . import config

logger = logging.getLogger("yunoballizer.uninstall")

REMOVABLE_DIRS = [config.CONFIG_DIR, config.APP_DATA_DIR]


def run(assume_yes: bool = False) -> None:
    existing = [d for d in REMOVABLE_DIRS if d.exists()]

    if not existing:
        print("Nothing to remove: no yunoballizer config or data directories found.")
        return

    print("This will permanently delete the following directories:")
    for d in existing:
        print(f"  - {d}")
    print(
        "\nNote: this includes all collected content under "
        f"{config.DATA_DIR}. This does not uninstall the Python package "
        "itself (run `pip uninstall yunoballizer` for that)."
    )

    if not assume_yes:
        answer = input("\nContinue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return

    for d in existing:
        shutil.rmtree(d, ignore_errors=True)
        print(f"Removed {d}")

    print(
        "\nDone. To fully remove yunoballizer, also run: "
        "pip uninstall yunoballizer"
    )
