from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yunoballizer import fetch


class FetchTests(unittest.TestCase):
    def test_fetch_adds_unique_normalized_saved_post_authors(self) -> None:
        posts = [
            SimpleNamespace(owner_username="Zeta"),
            SimpleNamespace(owner_username="alpha"),
            SimpleNamespace(owner_username="ALPHA"),
            SimpleNamespace(owner_username=""),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=object()),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nzeta\n")


if __name__ == "__main__":
    unittest.main()
