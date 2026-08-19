from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from yunoballizer import cli, storage
from yunoballizer.downloaders import instagram, tiktok, urls, youtube, ytdlp_helper
from yunoballizer.downloaders.budget import TotalBudget


class _FakeProfile:
    """A hashable stand-in for instaloader.Profile (needed for the {profile} set literal)."""

    def __init__(self, username: str, userid: int = 42) -> None:
        self.username = username
        self.userid = userid


class YtdlpHelperTests(unittest.TestCase):
    def test_writes_infojson_and_description_templates(self) -> None:
        ydl = Mock()
        ydl.__enter__ = Mock(return_value=ydl)
        ydl.__exit__ = Mock(return_value=False)

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(ytdlp_helper.yt_dlp, "YoutubeDL", return_value=ydl) as youtube_dl,
        ):
            root = Path(tmpdir)
            ytdlp_helper.download(
                "https://example.test/post",
                str(root / "video.%(ext)s"),
                root / "state" / "archive.txt",
                metadata_template=str(root / "metadata.%(ext)s"),
                caption_template=str(root / "caption.%(ext)s"),
            )

        options = youtube_dl.call_args.args[0]
        self.assertEqual(
            options["outtmpl"],
            {
                "default": str(root / "video.%(ext)s"),
                "infojson": str(root / "metadata.%(ext)s"),
                "description": str(root / "caption.%(ext)s"),
            },
        )
        self.assertTrue(options["writedescription"])
        self.assertFalse(options["allow_playlist_files"])
        ydl.download.assert_called_once_with(["https://example.test/post"])

    def test_on_item_done_fires_once_per_finished_file_with_its_post_dir(self) -> None:
        ydl = Mock()
        ydl.__enter__ = Mock(return_value=ydl)
        ydl.__exit__ = Mock(return_value=False)
        on_item_done = Mock()

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(ytdlp_helper.yt_dlp, "YoutubeDL", return_value=ydl) as youtube_dl,
        ):
            root = Path(tmpdir)
            ytdlp_helper.download(
                "https://example.test/post",
                str(root / "%(id)s" / "video.%(ext)s"),
                root / "state" / "archive.txt",
                on_item_done=on_item_done,
            )

        hook = youtube_dl.call_args.args[0]["progress_hooks"][0]
        post_dir = root / "vid1"

        hook({"status": "downloading", "filename": str(post_dir / "video.mp4")})
        on_item_done.assert_not_called()

        hook({"status": "finished", "filename": str(post_dir / "video.mp4")})
        on_item_done.assert_called_once_with(post_dir)

    def test_no_progress_hooks_option_when_on_item_done_omitted(self) -> None:
        ydl = Mock()
        ydl.__enter__ = Mock(return_value=ydl)
        ydl.__exit__ = Mock(return_value=False)

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(ytdlp_helper.yt_dlp, "YoutubeDL", return_value=ydl) as youtube_dl,
        ):
            ytdlp_helper.download(
                "https://example.test/post",
                str(Path(tmpdir) / "video.%(ext)s"),
                Path(tmpdir) / "state" / "archive.txt",
            )

        self.assertNotIn("progress_hooks", youtube_dl.call_args.args[0])


class CliParserTests(unittest.TestCase):
    def test_parser_accepts_skip_short_and_long_flags(self) -> None:
        short_args = cli.build_parser().parse_args(["download", "-s", "5", "-l", "10"])
        long_args = cli.build_parser().parse_args(["download", "--skip", "7"])

        self.assertEqual((short_args.skip, short_args.limit), (5, 10))
        self.assertEqual(long_args.skip, 7)

    def test_run_download_forwards_skip_to_account_downloaders(self) -> None:
        with (
            patch.object(cli.instagram, "harvest") as instagram_harvest,
            patch.object(cli.youtube, "harvest") as youtube_harvest,
            patch.object(cli.tiktok, "harvest") as tiktok_harvest,
            patch.object(cli.storage, "refresh_review", return_value=0),
        ):
            cli._run_download(limit=10, skip=5, accounts=["nasa"])

        for harvest in (instagram_harvest, youtube_harvest, tiktok_harvest):
            harvest.assert_called_once_with(limit=10, skip=5, accounts=["nasa"])

    def test_parser_accepts_new_download_flags(self) -> None:
        args = cli.build_parser().parse_args([
            "download",
            "-p", "instagram", "-p", "tiktok",
            "--since", "2026-01-01",
            "--until", "2026-06-30",
            "-t", "photo",
            "--total-limit", "50",
            "--delay", "5",
        ])

        self.assertEqual(args.platforms, ["instagram", "tiktok"])
        self.assertEqual(args.since, datetime.date(2026, 1, 1))
        self.assertEqual(args.until, datetime.date(2026, 6, 30))
        self.assertEqual(args.media_type, "photo")
        self.assertEqual(args.total_limit, 50)
        self.assertEqual(args.delay, 5)

    def test_parser_rejects_invalid_date(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["download", "--since", "01-01-2026"])

    def test_main_rejects_since_after_until(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(["download", "--since", "2026-06-30", "--until", "2026-01-01"])

    def test_run_download_restricts_to_selected_platforms(self) -> None:
        with (
            patch.object(cli.instagram, "harvest") as instagram_harvest,
            patch.object(cli.youtube, "harvest") as youtube_harvest,
            patch.object(cli.tiktok, "harvest") as tiktok_harvest,
            patch.object(cli.urls_mod, "harvest") as urls_harvest,
            patch.object(cli.storage, "refresh_review", return_value=0),
        ):
            cli._run_download(platforms=["instagram"])

        instagram_harvest.assert_called_once_with(limit=20, skip=0, accounts=None)
        youtube_harvest.assert_not_called()
        tiktok_harvest.assert_not_called()
        # urls.txt isn't tied to one platform, so a -p filter skips it too.
        urls_harvest.assert_not_called()

    def test_run_download_forwards_since_until_type_and_delay(self) -> None:
        since = datetime.date(2026, 1, 1)
        until = datetime.date(2026, 6, 30)
        with (
            patch.object(cli.instagram, "harvest") as instagram_harvest,
            patch.object(cli.youtube, "harvest") as youtube_harvest,
            patch.object(cli.tiktok, "harvest") as tiktok_harvest,
            patch.object(cli.urls_mod, "harvest"),
            patch.object(cli.storage, "refresh_review", return_value=0),
        ):
            cli._run_download(since=since, until=until, media_type="video", delay=5)

        for harvest in (instagram_harvest, youtube_harvest, tiktok_harvest):
            harvest.assert_called_once_with(
                limit=20, skip=0, accounts=None,
                since=since, until=until, media_type="video", sleep_seconds=5,
            )

    def test_run_download_shares_one_budget_across_platforms(self) -> None:
        with (
            patch.object(cli.instagram, "harvest") as instagram_harvest,
            patch.object(cli.youtube, "harvest") as youtube_harvest,
            patch.object(cli.tiktok, "harvest") as tiktok_harvest,
            patch.object(cli.urls_mod, "harvest"),
            patch.object(cli.storage, "refresh_review", return_value=0),
        ):
            cli._run_download(total_limit=30)

        budgets = {
            call.kwargs["budget"]
            for call in (
                instagram_harvest.call_args, youtube_harvest.call_args, tiktok_harvest.call_args,
            )
        }
        self.assertEqual(len(budgets), 1)
        self.assertIsInstance(budgets.pop(), TotalBudget)


class TotalBudgetTests(unittest.TestCase):
    def test_unlimited_when_no_limit_given(self) -> None:
        budget = TotalBudget(None)
        self.assertFalse(budget.exhausted)
        self.assertEqual(budget.take(20), 20)
        self.assertFalse(budget.exhausted)

    def test_caps_and_spends_across_calls(self) -> None:
        budget = TotalBudget(15)
        self.assertEqual(budget.take(20), 15)
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.take(5), 0)

    def test_splits_across_several_accounts(self) -> None:
        budget = TotalBudget(25)
        self.assertEqual(budget.take(20), 20)
        self.assertFalse(budget.exhausted)
        self.assertEqual(budget.take(20), 5)
        self.assertTrue(budget.exhausted)


class InstagramDownloadTests(unittest.TestCase):
    def test_uses_account_dirname_and_shortcode_scoped_filename_pattern(self) -> None:
        # {shortcode} deliberately lives in filename_pattern, not dirname_pattern:
        # Instaloader plain str.format()s dirname_pattern with only profile/target
        # in a couple of places outside per-post downloading (profile-level
        # metadata, the resume file), which would KeyError on {shortcode} there.
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(instagram.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(instagram.instaloader, "Instaloader") as instaloader_cls,
            patch.object(
                instagram.instaloader.Profile, "from_username",
                return_value=_FakeProfile("nasa"),
            ),
            patch.object(instagram.time, "sleep"),
            patch.object(instagram.storage, "organize_instagram_account"),
        ):
            loader = SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True)
            instaloader_cls.return_value = loader

            instagram.harvest(accounts=["nasa"], sleep_seconds=0)

            dirname_pattern = instaloader_cls.call_args.kwargs["dirname_pattern"]
            filename_pattern = instaloader_cls.call_args.kwargs["filename_pattern"]
            self.assertIn("{target}", dirname_pattern)
            self.assertNotIn("{shortcode}", dirname_pattern)
            self.assertEqual(filename_pattern, f"{{shortcode}}/{storage.INSTAGRAM_FILENAME_PATTERN}")

    def test_dirname_pattern_never_raises_when_formatted_without_a_post(self) -> None:
        # Regression test for the crash this shape avoids: Instaloader itself
        # calls `self.dirname_pattern.format(profile=..., target=...)` (a bare
        # str.format, not the post-aware formatter) before any post is ever
        # downloaded, e.g. to place profile-level metadata JSON.
        real_loader = instagram.instaloader.Instaloader(
            dirname_pattern=str(Path("out") / "{target}"),
            filename_pattern=f"{{shortcode}}/{storage.INSTAGRAM_FILENAME_PATTERN}",
        )
        real_loader.dirname_pattern.format(profile="nasa", target="nasa")

    def test_post_filter_skips_then_dedups_by_media_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir = Path(tmpdir)
            account_dir = sources_dir / "instagram" / "nasa"
            (account_dir / "already-downloaded" / "image.jpg").parent.mkdir(parents=True)
            (account_dir / "already-downloaded" / "image.jpg").touch()
            # A 3-item carousel interrupted after saving only 1 image: not
            # empty, but not complete either -- should be retried.
            (account_dir / "partial-carousel" / "image_01.jpg").parent.mkdir(parents=True)
            (account_dir / "partial-carousel" / "image_01.jpg").touch()

            loader = SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True)

            with (
                patch.object(instagram.instaloader, "Instaloader", return_value=loader),
                patch.object(
                    instagram.instaloader.Profile, "from_username",
                    return_value=_FakeProfile("nasa"),
                ),
                patch.object(instagram.time, "sleep"),
                patch.object(instagram.config, "SOURCES_DIR", sources_dir),
                patch.object(instagram.storage, "organize_instagram_account"),
            ):
                instagram.harvest(limit=2, skip=1, accounts=["nasa"], sleep_seconds=0)

            kwargs = loader.download_profiles.call_args.kwargs
            self.assertFalse(kwargs["profile_pic"])
            self.assertFalse(kwargs["fast_update"])
            self.assertEqual(kwargs["max_count"], 3)

            posts = [
                SimpleNamespace(shortcode="skip-me", mediacount=1),
                SimpleNamespace(shortcode="already-downloaded", mediacount=1),
                SimpleNamespace(shortcode="partial-carousel", mediacount=3),
                SimpleNamespace(shortcode="new-post", mediacount=1),
            ]
            self.assertEqual(
                [kwargs["post_filter"](p) for p in posts], [False, False, True, True]
            )

    def test_organize_is_called_after_each_account(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(instagram.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(
                instagram.instaloader, "Instaloader",
                return_value=SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True),
            ),
            patch.object(
                instagram.instaloader.Profile, "from_username",
                return_value=_FakeProfile("nasa"),
            ),
            patch.object(instagram.time, "sleep"),
            patch.object(instagram.storage, "organize_instagram_account") as organize,
        ):
            instagram.harvest(accounts=["nasa"], sleep_seconds=0)

        organize.assert_called_once_with(Path(tmpdir) / "instagram" / "nasa")

    def test_refresh_review_runs_after_each_account_not_just_at_the_end(self) -> None:
        # So an interrupted multi-account run still leaves already-finished
        # accounts' posts visible in review/, instead of only after the
        # whole run (across every platform) completes.
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(instagram.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(
                instagram.instaloader, "Instaloader",
                return_value=SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True),
            ),
            patch.object(
                instagram.instaloader.Profile, "from_username",
                side_effect=[_FakeProfile("a"), _FakeProfile("b")],
            ),
            patch.object(instagram.time, "sleep"),
            patch.object(instagram.storage, "organize_instagram_account"),
            patch.object(instagram.storage, "refresh_review") as refresh_review,
        ):
            instagram.harvest(accounts=["a", "b"], sleep_seconds=0)

        self.assertEqual(refresh_review.call_count, 2)

    def test_post_filter_honors_since_until_and_media_type(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(instagram.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(
                instagram.instaloader, "Instaloader",
                return_value=SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True),
            ),
            patch.object(
                instagram.instaloader.Profile, "from_username",
                return_value=_FakeProfile("nasa"),
            ),
            patch.object(instagram.time, "sleep"),
            patch.object(instagram.storage, "organize_instagram_account"),
        ):
            instagram.harvest(
                accounts=["nasa"], sleep_seconds=0,
                since=datetime.date(2026, 1, 1), until=datetime.date(2026, 6, 30),
                media_type="photo",
            )

            loader = instagram.instaloader.Instaloader.return_value
            post_filter = loader.download_profiles.call_args.kwargs["post_filter"]

            too_early = SimpleNamespace(
                shortcode="early", mediacount=1, is_video=False,
                date_utc=datetime.datetime(2025, 12, 31),
            )
            too_late = SimpleNamespace(
                shortcode="late", mediacount=1, is_video=False,
                date_utc=datetime.datetime(2026, 7, 1),
            )
            a_video = SimpleNamespace(
                shortcode="vid", mediacount=1, is_video=True,
                date_utc=datetime.datetime(2026, 3, 1),
            )
            a_photo = SimpleNamespace(
                shortcode="pic", mediacount=1, is_video=False,
                date_utc=datetime.datetime(2026, 3, 1),
            )
            self.assertFalse(post_filter(too_early))
            self.assertFalse(post_filter(too_late))
            self.assertFalse(post_filter(a_video))
            self.assertTrue(post_filter(a_photo))

    def test_budget_caps_max_count_and_stops_once_exhausted(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(instagram.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(
                instagram.instaloader, "Instaloader",
                return_value=SimpleNamespace(context=object(), download_profiles=Mock(), compress_json=True),
            ),
            patch.object(
                instagram.instaloader.Profile, "from_username",
                return_value=_FakeProfile("nasa"),
            ),
            patch.object(instagram.time, "sleep"),
            patch.object(instagram.storage, "organize_instagram_account"),
        ):
            budget = TotalBudget(3)
            instagram.harvest(accounts=["a", "b"], limit=20, sleep_seconds=0, budget=budget)

            loader = instagram.instaloader.Instaloader.return_value
            self.assertEqual(loader.download_profiles.call_count, 1)
            self.assertEqual(loader.download_profiles.call_args.kwargs["max_count"], 3)
            self.assertTrue(budget.exhausted)

    def test_removes_stray_profile_level_metadata_json_after_harvest(self) -> None:
        # Instaloader.download_profiles() unconditionally drops a
        # "<username>_<userid>.json[.xz]" profile-level metadata file in the
        # account root whenever save_metadata is on (which it always is here,
        # since that same flag also produces the per-post metadata this
        # project relies on) -- harvest() should clean that stray file up.
        for compress_json, ext in ((True, ".json.xz"), (False, ".json")):
            with self.subTest(compress_json=compress_json):
                with tempfile.TemporaryDirectory() as tmpdir:
                    sources_dir = Path(tmpdir)
                    account_dir = sources_dir / "instagram" / "nasa"
                    account_dir.mkdir(parents=True)
                    stray = account_dir / f"nasa_42{ext}"

                    def fake_download_profiles(*args, **kwargs) -> None:
                        stray.touch()

                    loader = SimpleNamespace(
                        context=object(),
                        download_profiles=Mock(side_effect=fake_download_profiles),
                        compress_json=compress_json,
                    )

                    with (
                        patch.object(instagram.instaloader, "Instaloader", return_value=loader),
                        patch.object(
                            instagram.instaloader.Profile, "from_username",
                            return_value=_FakeProfile("nasa"),
                        ),
                        patch.object(instagram.time, "sleep"),
                        patch.object(instagram.config, "SOURCES_DIR", sources_dir),
                        patch.object(instagram.storage, "organize_instagram_account"),
                    ):
                        instagram.harvest(accounts=["nasa"], sleep_seconds=0)

                    self.assertFalse(stray.exists())


class YoutubeTiktokDownloadTests(unittest.TestCase):
    def test_youtube_uses_one_based_skip_range_and_id_scoped_templates(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(youtube.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(youtube.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(youtube, "download") as download,
            patch.object(youtube.storage, "organize_ytdlp_tree") as organize,
        ):
            youtube.harvest(limit=10, skip=5, accounts=["@nasa"])

        self.assertEqual(download.call_args.args[3], {"playliststart": 6, "playlistend": 15})
        self.assertIn("/%(id)s/video.%(ext)s", download.call_args.args[1])
        self.assertIn("/%(id)s/metadata.%(ext)s", download.call_args.kwargs["metadata_template"])
        self.assertIn("/%(id)s/caption.%(ext)s", download.call_args.kwargs["caption_template"])
        organize.assert_called_once_with(Path(tmpdir) / "youtube")

    def test_tiktok_uses_one_based_skip_range_and_id_scoped_templates(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(tiktok.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(tiktok.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(tiktok, "download") as download,
            patch.object(tiktok.storage, "organize_ytdlp_tree") as organize,
            patch.object(tiktok.time, "sleep"),
        ):
            tiktok.harvest(limit=10, skip=5, accounts=["nasa"], sleep_seconds=0)

        self.assertEqual(download.call_args.args[3], {"playliststart": 6, "playlistend": 15})
        self.assertIn("/%(id)s/video.%(ext)s", download.call_args.args[1])
        self.assertIn("/%(id)s/metadata.%(ext)s", download.call_args.kwargs["metadata_template"])
        self.assertIn("/%(id)s/caption.%(ext)s", download.call_args.kwargs["caption_template"])
        organize.assert_called_once_with(Path(tmpdir) / "tiktok")

    def test_youtube_forwards_since_until_as_yt_dlp_date_opts(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(youtube.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(youtube.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(youtube, "download") as download,
            patch.object(youtube.storage, "organize_ytdlp_tree"),
        ):
            youtube.harvest(
                accounts=["@nasa"],
                since=datetime.date(2026, 1, 1), until=datetime.date(2026, 6, 30),
            )

        extra_opts = download.call_args.args[3]
        self.assertEqual(extra_opts["dateafter"], "20260101")
        self.assertEqual(extra_opts["datebefore"], "20260630")

    def test_youtube_skips_entirely_for_type_photo(self) -> None:
        with patch.object(youtube, "download") as download:
            youtube.harvest(accounts=["@nasa"], media_type="photo")

        download.assert_not_called()

    def test_tiktok_skips_entirely_for_type_photo(self) -> None:
        with patch.object(tiktok, "download") as download:
            tiktok.harvest(accounts=["nasa"], media_type="photo")

        download.assert_not_called()

    def test_youtube_wires_up_incremental_review_refresh(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(youtube.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(youtube.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(youtube, "download") as download,
            patch.object(youtube.storage, "organize_ytdlp_tree"),
        ):
            youtube.harvest(accounts=["@nasa"])

        self.assertEqual(download.call_args.kwargs["on_item_done"], youtube.storage.refresh_new_ytdlp_post)

    def test_tiktok_wires_up_incremental_review_refresh(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(tiktok.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(tiktok.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(tiktok, "download") as download,
            patch.object(tiktok.storage, "organize_ytdlp_tree"),
            patch.object(tiktok.time, "sleep"),
        ):
            tiktok.harvest(accounts=["nasa"])

        self.assertEqual(download.call_args.kwargs["on_item_done"], tiktok.storage.refresh_new_ytdlp_post)

    def test_urls_wires_up_incremental_review_refresh(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(urls.config, "CONFIG_DIR", Path(tmpdir)),
            patch.object(urls.config, "SOURCES_DIR", Path(tmpdir) / "sources"),
            patch.object(urls.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(urls, "download") as download,
            patch.object(urls.storage, "organize_ytdlp_tree"),
        ):
            (Path(tmpdir) / "urls.txt").write_text("https://example.test/post\n")
            urls.harvest()

        self.assertEqual(download.call_args.kwargs["on_item_done"], urls.storage.refresh_new_ytdlp_post)

    def test_tiktok_budget_caps_playlistend_and_stops_once_exhausted(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(tiktok.config, "SOURCES_DIR", Path(tmpdir)),
            patch.object(tiktok.config, "ARCHIVE_DIR", Path(tmpdir) / "archives"),
            patch.object(tiktok, "download") as download,
            patch.object(tiktok.storage, "organize_ytdlp_tree"),
            patch.object(tiktok.time, "sleep"),
        ):
            budget = TotalBudget(3)
            tiktok.harvest(accounts=["a", "b"], limit=20, budget=budget)

        download.assert_called_once()
        self.assertEqual(download.call_args.args[3]["playlistend"], 3)
        self.assertTrue(budget.exhausted)


if __name__ == "__main__":
    unittest.main()
