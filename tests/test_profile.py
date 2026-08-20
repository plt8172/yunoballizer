from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer.commands import profile


class ProfileTests(unittest.TestCase):
    def test_profile_reads_downloaded_instagram_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            post_dir = root / "data" / "instagram" / "creator" / "post1"
            post_dir.mkdir(parents=True)
            (post_dir / "caption.txt").write_text("Street photo #Seoul #Night", encoding="utf-8")
            config_dir.mkdir()

            with (
                patch.object(profile.config, "CONFIG_DIR", config_dir),
                patch.object(profile.config, "SOURCES_DIR", root / "data"),
                patch.object(profile.config, "DERIVED_DIR", root / "derived"),
            ):
                result = profile.build()

            stored = json.loads(
                (root / "derived" / profile.PROFILE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(result, stored)
            self.assertEqual(result["source_post_count"], 1)
            self.assertIn("seoul", result["top_hashtags"])


if __name__ == "__main__":
    unittest.main()
