from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import expand


class ExpandTests(unittest.TestCase):
    def test_expand_scans_all_downloaded_instagram_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            data_dir = root / "data"
            captions_dir = data_dir / "instagram"
            (captions_dir / "one" / "post1").mkdir(parents=True)
            (captions_dir / "two" / "post2").mkdir(parents=True)
            (captions_dir / "one" / "post1" / "caption.txt").write_text(
                "hello @Alpha", encoding="utf-8"
            )
            (captions_dir / "two" / "post2" / "caption.txt").write_text(
                "@beta and @ALPHA", encoding="utf-8"
            )

            with (
                patch.object(expand.config, "CONFIG_DIR", config_dir),
                patch.object(expand.config, "SOURCES_DIR", data_dir),
            ):
                added = expand.scan_caption_mentions()

            accounts_file = config_dir / "instagram" / "accounts.txt"
            self.assertEqual(added, 2)
            self.assertEqual(accounts_file.read_text(encoding="utf-8"), "alpha\nbeta\n")


if __name__ == "__main__":
    unittest.main()
