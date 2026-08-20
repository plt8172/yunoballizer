from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yunoballizer import fetch


class SavedSourceTests(unittest.TestCase):
    def test_adds_unique_normalized_saved_post_authors(self) -> None:
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

    def test_resolves_each_unique_owner_id_only_once(self) -> None:
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

    def test_skips_owners_that_fail_to_resolve(self) -> None:
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

    def test_limit_caps_how_many_saved_posts_are_read(self) -> None:
        posts = [SimpleNamespace(owner_id=i) for i in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch(
                    "instaloader.Profile.from_id",
                    side_effect=lambda context, owner_id: SimpleNamespace(username=f"user{owner_id}"),
                ) as from_id,
            ):
                added = fetch.run(limit=2)

            self.assertEqual(added, 2)
            self.assertEqual(from_id.call_count, 2)


class FollowingSourceTests(unittest.TestCase):
    def test_adds_followee_usernames_without_extra_resolution(self) -> None:
        followees = [SimpleNamespace(username="Zeta"), SimpleNamespace(username="alpha")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_followees", return_value=followees),
            ):
                added = fetch.run(sources=["following"])

            accounts_file = config_dir / "instagram" / "accounts.txt"
            self.assertEqual(added, 2)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nzeta\n")

    def test_limit_caps_how_many_followees_are_read(self) -> None:
        followees = [SimpleNamespace(username=f"user{i}") for i in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_followees", return_value=followees),
            ):
                added = fetch.run(limit=2, sources=["following"])

            self.assertEqual(added, 2)

    def test_can_combine_saved_and_following(self) -> None:
        posts = [SimpleNamespace(owner_id=1)]
        followees = [SimpleNamespace(username="natgeo")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch.object(fetch, "_followees", return_value=followees),
                patch("instaloader.Profile.from_id", return_value=SimpleNamespace(username="nasa")),
            ):
                added = fetch.run(sources=["saved", "following"])

            accounts_file = config_dir / "instagram" / "accounts.txt"
            self.assertEqual(added, 2)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "nasa\nnatgeo\n")


class SourceValidationTests(unittest.TestCase):
    def test_unsupported_source_raises_with_a_reason(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            fetch.run(sources=["liked"])
        self.assertIn("liked", str(ctx.exception))

    def test_unknown_source_raises(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            fetch.run(sources=["bogus"])
        self.assertIn("bogus", str(ctx.exception))


class SyncTests(unittest.TestCase):
    def test_sync_removes_accounts_no_longer_in_the_source(self) -> None:
        posts = [SimpleNamespace(owner_id=1)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("# comment\nalpha\nnasa\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch("instaloader.Profile.from_id", return_value=SimpleNamespace(username="nasa")),
            ):
                added = fetch.run(sync=True)

            self.assertEqual(added, 0)  # nasa was already present
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "# comment\nnasa\n")

    def test_sync_with_nothing_found_empties_the_matching_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=[]),
            ):
                added = fetch.run(sync=True)

            self.assertEqual(added, 0)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "")

    def test_without_sync_stale_accounts_are_left_alone(self) -> None:
        posts = [SimpleNamespace(owner_id=1)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch("instaloader.Profile.from_id", return_value=SimpleNamespace(username="nasa")),
            ):
                fetch.run(sync=False)

            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nnasa\n")


if __name__ == "__main__":
    unittest.main()
