from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yunoballizer import fetch


class _FakePost:
    """Stands in for instaloader's Post: owner_id is free, owner_username
    is a request that's paid the first time it's read on a given instance
    (tracked via access_count so tests can assert dedup actually happens)."""

    def __init__(self, owner_id, username=None, raises=False):
        self.owner_id = owner_id
        self._username = username
        self._raises = raises
        self.access_count = 0

    @property
    def owner_username(self):
        self.access_count += 1
        if self._raises:
            raise RuntimeError("blocked")
        return self._username


class SavedSourceTests(unittest.TestCase):
    def test_adds_unique_normalized_saved_post_authors(self) -> None:
        posts = [
            _FakePost(owner_id=1, username="Zeta"),
            _FakePost(owner_id=2, username="alpha"),
            _FakePost(owner_id=3, username="ALPHA"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nzeta\n")

    def test_resolves_each_unique_owner_id_only_once(self) -> None:
        # Saving several posts from the same account is the common case --
        # resolving should cost one request per unique owner, not one per
        # post, and it should be the *first* post for that owner that pays
        # it (later ones for the same owner must never be touched).
        posts = [_FakePost(owner_id=1, username="alpha") for _ in range(4)]
        posts.append(_FakePost(owner_id=1, raises=True))

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)
            self.assertEqual(posts[0].access_count, 1)
            self.assertEqual(posts[-1].access_count, 0)

    def test_skips_owners_that_fail_to_resolve(self) -> None:
        posts = [_FakePost(owner_id=1, raises=True), _FakePost(owner_id=2, username="alpha")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run()

            self.assertEqual(added, 1)

    def test_limit_caps_how_many_saved_posts_are_read(self) -> None:
        posts = [_FakePost(owner_id=i, username=f"user{i}") for i in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run(limit=2)

            self.assertEqual(added, 2)
            self.assertEqual(sum(p.access_count for p in posts), 2)


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
        posts = [_FakePost(owner_id=1, username="nasa")]
        followees = [SimpleNamespace(username="natgeo")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch.object(fetch, "_followees", return_value=followees),
            ):
                added = fetch.run(sources=["saved", "following"])

            accounts_file = config_dir / "instagram" / "accounts.txt"
            self.assertEqual(added, 2)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "nasa\nnatgeo\n")


class TotalLimitTests(unittest.TestCase):
    def test_caps_the_combined_result_across_sources(self) -> None:
        # --limit alone would let each source contribute up to its own cap
        # (here, both saved and following would each get through); only
        # total_limit caps the merged result to a true grand total.
        posts = [_FakePost(owner_id=1, username="nasa")]
        followees = [SimpleNamespace(username="natgeo")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
                patch.object(fetch, "_followees", return_value=followees),
            ):
                added = fetch.run(sources=["saved", "following"], total_limit=1)

            accounts_file = config_dir / "instagram" / "accounts.txt"
            self.assertEqual(added, 1)
            # Deterministic (alphabetical), not source-order-dependent.
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "nasa\n")

    def test_agrees_with_limit_for_a_single_source(self) -> None:
        posts = [_FakePost(owner_id=i, username=f"user{i}") for i in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run(total_limit=2)

            self.assertEqual(added, 2)


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
        posts = [_FakePost(owner_id=1, username="nasa")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("# comment\nalpha\nnasa\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
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
        posts = [_FakePost(owner_id=1, username="nasa")]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                fetch.run(sync=False)

            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nnasa\n")

    def test_sync_does_not_remove_accounts_when_resolution_failed(self) -> None:
        # "nasa" resolves fine and should still get confirmed/kept; "alpha"
        # is a *different*, still-genuinely-saved account whose owner_id
        # happened to fail to resolve this run (rate limit, etc). Since
        # discovery is incomplete, --sync must not treat alpha's absence
        # from `authors` as proof it was unsaved and delete it.
        posts = [_FakePost(owner_id=1, username="nasa"), _FakePost(owner_id=2, raises=True)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\nnasa\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run(sync=True)

            self.assertEqual(added, 0)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nnasa\n")

    def test_sync_still_adds_successfully_resolved_accounts_despite_other_failures(self) -> None:
        posts = [_FakePost(owner_id=1, username="natgeo"), _FakePost(owner_id=2, raises=True)]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            accounts_file = config_dir / "instagram" / "accounts.txt"
            accounts_file.parent.mkdir(parents=True)
            accounts_file.write_text("alpha\n", encoding="utf-8")

            with (
                patch.object(fetch.config, "CONFIG_DIR", config_dir),
                patch.object(fetch.auth, "get_loader", return_value=SimpleNamespace(context=object())),
                patch.object(fetch, "_saved_posts", return_value=posts),
            ):
                added = fetch.run(sync=True)

            self.assertEqual(added, 1)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nnatgeo\n")


if __name__ == "__main__":
    unittest.main()
