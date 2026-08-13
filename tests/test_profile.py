from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import profile


class ProfileTests(unittest.TestCase):
    def test_profile_reads_downloaded_instagram_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            captions_dir = root / "data" / "instagram" / "accounts" / "creator"
            captions_dir.mkdir(parents=True)
            captions_dir.joinpath("post.txt").write_text(
                "Street photo #Seoul #Night", encoding="utf-8"
            )
            config_dir.mkdir()

            with (
                patch.object(profile.config, "CONFIG_DIR", config_dir),
                patch.object(profile.config, "DATA_DIR", root / "data"),
            ):
                result = profile.build()

            stored = json.loads(
                (config_dir / profile.PROFILE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(result, stored)
            self.assertEqual(result["source_post_count"], 1)
            self.assertIn("seoul", result["top_hashtags"])


if __name__ == "__main__":
    unittest.main()
