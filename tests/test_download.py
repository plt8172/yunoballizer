from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from yunoballizer import cli, storage
from yunoballizer.downloaders import instagram, tiktok, youtube, ytdlp_helper


class _FakeProfile:
    """A hashable stand-in for instaloader.Profile (needed for the {profile} set literal)."""

    def __init__(self, username: str) -> None:
        self.username = username


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
        ydl.download.assert_called_once_with(["https://example.test/post"])


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
            loader = SimpleNamespace(context=object(), download_profiles=Mock())
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

            loader = SimpleNamespace(context=object(), download_profiles=Mock())

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
                return_value=SimpleNamespace(context=object(), download_profiles=Mock()),
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


if __name__ == "__main__":
    unittest.main()
