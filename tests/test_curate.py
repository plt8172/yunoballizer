from __future__ import annotations

import json
import lzma
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config, curate


class FindCaptionTests(unittest.TestCase):
    def test_reads_sibling_caption_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            post_dir = Path(tmpdir)
            media = post_dir / "image_01.jpg"
            media.touch()
            (post_dir / "caption.txt").write_text("hello world", encoding="utf-8")

            self.assertEqual(curate._find_caption(media), "hello world")

    def test_falls_back_to_compressed_metadata_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            post_dir = Path(tmpdir)
            media = post_dir / "video.mp4"
            media.touch()
            (post_dir / "metadata.json.xz").write_bytes(
                lzma.compress(json.dumps({"description": "video caption"}).encode("utf-8"))
            )

            self.assertEqual(curate._find_caption(media), "video caption")

    def test_returns_empty_string_when_nothing_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "video.mp4"
            media.touch()
            self.assertEqual(curate._find_caption(media), "")


class CurateRunTests(unittest.TestCase):
    def test_run_copies_kept_media_with_collision_safe_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir = root / "sources"
            curated_dir = root / "curated"
            derived_dir = root / "derived"
            state_dir = root / "state"

            for account in ("one", "two"):
                post_dir = sources_dir / "instagram" / account / "postid"
                post_dir.mkdir(parents=True)
                (post_dir / "video.mp4").write_bytes(b"data")
                (post_dir / "caption.txt").write_text("#seoul night walk", encoding="utf-8")

            profile_path = derived_dir / "taste_profile.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(
                json.dumps({"top_hashtags": ["seoul"], "top_keywords": ["night"]}),
                encoding="utf-8",
            )

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "CURATED_DIR", curated_dir),
                patch.object(config, "DERIVED_DIR", derived_dir),
                patch.object(config, "CURATION_LOG_PATH", state_dir / "curation_log.json"),
            ):
                curate.run()

            curated_files = sorted(curated_dir.iterdir())
            self.assertEqual(len(curated_files), 2)
            self.assertEqual(len({p.name for p in curated_files}), 2)


if __name__ == "__main__":
    unittest.main()
