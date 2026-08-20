from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer.commands import urls


class UrlsTests(unittest.TestCase):
    def test_add_strips_whitespace_and_dedupes_exact_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(urls.config, "CONFIG_DIR", Path(tmpdir)):
                self.assertTrue(urls.add("  https://example.com/post?id=1  "))
                self.assertFalse(urls.add("https://example.com/post?id=1"))
                self.assertEqual(urls.list_urls(), ["https://example.com/post?id=1"])

    def test_remove_preserves_other_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            path = config_dir / "inputs.json"
            path.write_text(json.dumps({
                "instagram": ["nasa"],
                "youtube": [],
                "tiktok": [],
                "urls": ["https://example.com/one", "https://example.com/two"],
            }),
                encoding="utf-8",
            )
            with patch.object(urls.config, "CONFIG_DIR", config_dir):
                self.assertTrue(urls.remove("https://example.com/one"))

            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["instagram"], ["nasa"])
            self.assertEqual(stored["urls"], ["https://example.com/two"])

    def test_remove_missing_url_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(urls.config, "CONFIG_DIR", Path(tmpdir)):
                self.assertFalse(urls.remove("https://example.com/missing"))

    def test_rejects_relative_and_non_http_urls(self) -> None:
        for value in ("example.com/post", "/local/path", "ftp://example.com/file", ""):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit):
                    urls.add(value)

    def test_preserves_url_case_and_fragment(self) -> None:
        value = "https://Example.com/Post#Section"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(urls.config, "CONFIG_DIR", Path(tmpdir)):
                urls.add(value)
                self.assertEqual(urls.list_urls(), [value])


if __name__ == "__main__":
    unittest.main()
