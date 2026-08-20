from __future__ import annotations

import json
import lzma
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config, storage


def _write(path: Path, content: bytes | str = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)


class OrganizeInstagramTests(unittest.TestCase):
    def test_single_image_post_gets_canonical_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            account_dir = Path(tmpdir) / "nasa"
            post_dir = account_dir / "ShortcodeA"
            _write(post_dir / "post.jpg")
            _write(post_dir / "post.txt", "a caption")
            _write(post_dir / "post.json.xz", lzma.compress(b'{"shortcode": "ShortcodeA"}'))

            storage.organize_instagram_account(account_dir)

            self.assertEqual(
                sorted(p.name for p in post_dir.iterdir()),
                ["caption.txt", "image.jpg", "metadata.json.xz"],
            )
            self.assertEqual((post_dir / "caption.txt").read_text(), "a caption")

    def test_carousel_post_numbers_images_and_leaves_lone_video_unnumbered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            account_dir = Path(tmpdir) / "nasa"
            post_dir = account_dir / "ShortcodeB"
            _write(post_dir / "post_1.jpg", "first-image")
            _write(post_dir / "post_2.mp4", "the-video")
            _write(post_dir / "post_3.jpg", "second-image")
            _write(post_dir / "post.txt", "carousel caption")
            _write(post_dir / "post.json.xz", lzma.compress(b"{}"))

            storage.organize_instagram_account(account_dir)

            self.assertEqual(
                sorted(p.name for p in post_dir.iterdir()),
                ["caption.txt", "image_01.jpg", "image_02.jpg", "metadata.json.xz", "video.mp4"],
            )
            self.assertEqual((post_dir / "image_01.jpg").read_bytes(), b"first-image")
            self.assertEqual((post_dir / "image_02.jpg").read_bytes(), b"second-image")
            self.assertEqual((post_dir / "video.mp4").read_bytes(), b"the-video")

    def test_already_organized_post_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            account_dir = Path(tmpdir) / "nasa"
            post_dir = account_dir / "ShortcodeA"
            _write(post_dir / "image.jpg", "img")
            _write(post_dir / "caption.txt", "cap")

            storage.organize_instagram_account(account_dir)

            self.assertEqual(sorted(p.name for p in post_dir.iterdir()), ["caption.txt", "image.jpg"])

    def test_drops_loose_files_directly_in_account_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            account_dir = Path(tmpdir) / "nasa"
            post_dir = account_dir / "ShortcodeA"
            _write(post_dir / "image.jpg", "img")
            # Instaloader's own profile-level metadata, written straight
            # into the account dir rather than any post's subdirectory.
            _write(account_dir / "nasa_123456.json.xz", b"not a post")

            storage.organize_instagram_account(account_dir)

            self.assertEqual([p.name for p in account_dir.iterdir()], ["ShortcodeA"])
            self.assertTrue((post_dir / "image.jpg").exists())


class OrganizeYtdlpTests(unittest.TestCase):
    def test_post_dir_compresses_metadata_and_renames_caption(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            post_dir = Path(tmpdir) / "vid123"
            _write(post_dir / "video.mp4", "video-bytes")
            _write(post_dir / "metadata.info.json", '{"description": "hi"}')
            _write(post_dir / "caption.description", "hi")

            storage.organize_ytdlp_post_dir(post_dir)

            self.assertEqual(
                sorted(p.name for p in post_dir.iterdir()),
                ["caption.txt", "metadata.json.xz", "video.mp4"],
            )
            self.assertEqual((post_dir / "caption.txt").read_text(), "hi")
            decompressed = lzma.open(post_dir / "metadata.json.xz").read()
            self.assertEqual(json.loads(decompressed), {"description": "hi"})

    def test_organize_ytdlp_tree_walks_every_post_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for uploader, video_id in (("alice", "v1"), ("bob", "v2")):
                post_dir = root / uploader / video_id
                _write(post_dir / "video.mp4", "x")
                _write(post_dir / "metadata.info.json", "{}")

            storage.organize_ytdlp_tree(root)

            for uploader, video_id in (("alice", "v1"), ("bob", "v2")):
                self.assertTrue((root / uploader / video_id / "metadata.json.xz").exists())

    def test_refresh_new_ytdlp_post_organizes_and_adds_to_review_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            downloaded_dir = Path(tmpdir) / "downloaded"
            review_dir = Path(tmpdir) / "review"
            post_dir = downloaded_dir / "youtube" / "creator" / "vid1"
            _write(post_dir / "video.mp4", "x")
            _write(post_dir / "metadata.info.json", "{}")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded_dir),
                patch.object(config, "REVIEW_DIR", review_dir),
            ):
                storage.refresh_new_ytdlp_post(post_dir)

                self.assertTrue((post_dir / "metadata.json.xz").exists())
                links = list(review_dir.iterdir())
                self.assertEqual(len(links), 1)
                self.assertTrue(links[0].resolve() == (post_dir / "video.mp4").resolve())


class FindCaptionTests(unittest.TestCase):
    def test_reads_sibling_caption_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            post_dir = Path(tmpdir)
            media = post_dir / "image_01.jpg"
            media.touch()
            (post_dir / "caption.txt").write_text("hello world", encoding="utf-8")

            self.assertEqual(storage.find_caption(media), "hello world")

    def test_falls_back_to_compressed_metadata_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            post_dir = Path(tmpdir)
            media = post_dir / "video.mp4"
            media.touch()
            (post_dir / "metadata.json.xz").write_bytes(
                lzma.compress(json.dumps({"description": "video caption"}).encode("utf-8"))
            )

            self.assertEqual(storage.find_caption(media), "video caption")

    def test_returns_empty_string_when_nothing_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "video.mp4"
            media.touch()
            self.assertEqual(storage.find_caption(media), "")


class ReviewLinkTests(unittest.TestCase):
    def test_review_link_name_embeds_identifying_parts(self) -> None:
        name = storage.review_link_name(Path("instagram/nasa/ShortcodeA/image_01.jpg"))
        self.assertTrue(name.startswith("instagram-nasa-ShortcodeA-image_01-"))
        self.assertTrue(name.endswith(".jpg"))

    def test_review_link_name_is_collision_safe_despite_sanitization(self) -> None:
        name_a = storage.review_link_name(Path("instagram/nasa one/ShortcodeA/video.mp4"))
        name_b = storage.review_link_name(Path("instagram/nasa_one/ShortcodeA/video.mp4"))
        self.assertNotEqual(name_a, name_b)

    def test_refresh_review_links_media_and_skips_profile_pics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            downloaded_dir = Path(tmpdir) / "downloaded"
            review_dir = Path(tmpdir) / "review"
            _write(downloaded_dir / "instagram" / "nasa" / "ABC123" / "image_01.jpg")
            _write(downloaded_dir / "instagram" / "nasa" / "ABC123" / "video.mp4")
            _write(downloaded_dir / "instagram" / "nasa" / "ABC123" / "old_profile_pic.jpg")
            _write(downloaded_dir / "tiktok" / "acct" / "vid1" / "video.mp4")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded_dir),
                patch.object(config, "REVIEW_DIR", review_dir),
            ):
                added = storage.refresh_review()

                self.assertEqual(added, 3)
                links = list(review_dir.iterdir())
                self.assertEqual(len(links), 3)
                for link in links:
                    self.assertTrue(link.is_symlink())
                    self.assertTrue(link.exists())

                # Idempotent: re-running adds nothing new.
                self.assertEqual(storage.refresh_review(), 0)

    def test_review_survives_deletion_and_regenerates_from_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            downloaded_dir = Path(tmpdir) / "downloaded"
            review_dir = Path(tmpdir) / "review"
            media = downloaded_dir / "youtube" / "creator" / "vid1" / "video.mp4"
            _write(media)

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded_dir),
                patch.object(config, "REVIEW_DIR", review_dir),
            ):
                self.assertEqual(storage.refresh_review(), 1)
                for link in review_dir.iterdir():
                    link.unlink()
                self.assertEqual(len(list(review_dir.iterdir())), 0)

                self.assertEqual(storage.refresh_review(), 1)
                links = list(review_dir.iterdir())
                self.assertEqual(len(links), 1)
                self.assertTrue(links[0].resolve() == media.resolve())

    def test_refresh_review_prunes_dangling_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            downloaded_dir = Path(tmpdir) / "downloaded"
            review_dir = Path(tmpdir) / "review"
            media = downloaded_dir / "tiktok" / "acct" / "vid1" / "video.mp4"
            _write(media)

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded_dir),
                patch.object(config, "REVIEW_DIR", review_dir),
            ):
                storage.refresh_review()
                media.unlink()
                storage.refresh_review()
                self.assertEqual(len(list(review_dir.iterdir())), 0)


class ReviewProgressTests(unittest.TestCase):
    def test_accumulates_across_many_refresh_calls(self) -> None:
        # Regression test: a long download run refreshes review/ many times
        # as it goes (once per account, once per post) so already-finished
        # items stay browsable even if the run is interrupted -- but that
        # means refresh_review() itself only ever reports what *that* call
        # added, so a naive single trailing call for a final summary always
        # reports 0. ReviewProgress must sum every call instead.
        with tempfile.TemporaryDirectory() as tmpdir:
            downloaded_dir = Path(tmpdir) / "downloaded"
            review_dir = Path(tmpdir) / "review"
            _write(downloaded_dir / "youtube" / "creator" / "vid1" / "video.mp4")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded_dir),
                patch.object(config, "REVIEW_DIR", review_dir),
            ):
                progress = storage.ReviewProgress()

                # First item lands (e.g. one account/post finishing).
                self.assertEqual(progress.refresh(), 1)
                self.assertEqual(progress.total, 1)

                # Second item lands later in the same run.
                _write(downloaded_dir / "instagram" / "nasa" / "post1" / "image.jpg")
                self.assertEqual(progress.refresh(), 1)
                self.assertEqual(progress.total, 2)

                # A trailing refresh with nothing new to add doesn't lose the total.
                self.assertEqual(progress.refresh(), 0)
                self.assertEqual(progress.total, 2)

    def test_fresh_instance_starts_at_zero(self) -> None:
        self.assertEqual(storage.ReviewProgress().total, 0)


if __name__ == "__main__":
    unittest.main()
