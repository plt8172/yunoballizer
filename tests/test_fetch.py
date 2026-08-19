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
            SimpleNamespace(owner_id=1),
            SimpleNamespace(owner_id=2),
            SimpleNamespace(owner_id=3),
        ]
        usernames = {1: "Zeta", 2: "alpha", 3: "ALPHA"}

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch(
                    "instaloader.Profile.from_id",
                    side_effect=lambda context, owner_id: SimpleNamespace(username=usernames[owner_id]),
                ),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nzeta\n")

    def test_fetch_resolves_each_unique_owner_id_only_once(self) -> None:
        # Saving several posts from the same account is the common case --
        # resolving should cost one request per unique owner, not one per post.
        posts = [SimpleNamespace(owner_id=1) for _ in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch(
                    "instaloader.Profile.from_id",
                    return_value=SimpleNamespace(username="alpha"),
                ) as from_id,
            ):
                added = fetch.run()

            self.assertEqual(added, 1)
            self.assertEqual(from_id.call_count, 1)

    def test_fetch_skips_owners_that_fail_to_resolve(self) -> None:
        posts = [SimpleNamespace(owner_id=1), SimpleNamespace(owner_id=2)]

        def fake_from_id(context, owner_id):
            if owner_id == 1:
                raise Exception("blocked")
            return SimpleNamespace(username="alpha")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch("instaloader.Profile.from_id", side_effect=fake_from_id),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)


if __name__ == "__main__":
    unittest.main()
