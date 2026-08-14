from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from yunoballizer import cli
from yunoballizer.downloaders import instagram, tiktok, youtube


class SkipTests(unittest.TestCase):
    def test_parser_and_dispatch_accept_skip(self) -> None:
        args = cli.build_parser().parse_args(["download", "-s", "5", "-l", "10"])
        self.assertEqual((args.skip, args.limit), (5, 10))

        review = SimpleNamespace(refresh_review=Mock(return_value=0))
        with (
            patch.object(cli.instagram, "harvest") as instagram_harvest,
            patch.object(cli.youtube, "harvest") as youtube_harvest,
            patch.object(cli.tiktok, "harvest") as tiktok_harvest,
            patch.object(cli, "storage", review, create=True),
        ):
            cli._run_download(limit=10, skip=5, accounts=["nasa"])

        for harvest in (instagram_harvest, youtube_harvest, tiktok_harvest):
            harvest.assert_called_once_with(limit=10, skip=5, accounts=["nasa"])

    def test_instagram_skips_before_applying_limit(self) -> None:
        profile = type("Profile", (), {"username": "nasa"})()
        loader = SimpleNamespace(context=object(), download_profiles=Mock())

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            root = Path(tmpdir)
            stack.enter_context(
                patch.object(instagram.instaloader, "Instaloader", return_value=loader)
            )
            stack.enter_context(
                patch.object(instagram.instaloader.Profile, "from_username", return_value=profile)
            )
            stack.enter_context(patch.object(instagram.time, "sleep"))
            stack.enter_context(patch.object(instagram.config, "DATA_DIR", root))
            stack.enter_context(patch.object(instagram.config, "SOURCES_DIR", root, create=True))
            instagram.harvest(limit=2, skip=2, accounts=["nasa"], sleep_seconds=0)

        options = loader.download_profiles.call_args.kwargs
        posts = [SimpleNamespace(shortcode=f"post-{index}") for index in range(4)]
        self.assertEqual(options["max_count"], 4)
        self.assertEqual(
            [options["post_filter"](post) for post in posts],
            [False, False, True, True],
        )

    def test_ytdlp_downloaders_use_one_based_skip_range(self) -> None:
        for downloader, account in ((youtube, "@nasa"), (tiktok, "nasa")):
            with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
                root = Path(tmpdir)
                stack.enter_context(patch.object(downloader.config, "DATA_DIR", root))
                stack.enter_context(
                    patch.object(downloader.config, "SOURCES_DIR", root, create=True)
                )
                stack.enter_context(
                    patch.object(downloader.config, "ARCHIVE_DIR", root, create=True)
                )
                if downloader is tiktok:
                    stack.enter_context(patch.object(tiktok.time, "sleep"))
                download = stack.enter_context(patch.object(downloader, "download"))

                downloader.harvest(limit=10, skip=5, accounts=[account])

            self.assertEqual(
                download.call_args.args[3],
                {"playliststart": 6, "playlistend": 15},
            )


if __name__ == "__main__":
    unittest.main()
