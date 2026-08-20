from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer.commands import accounts


class AccountsTests(unittest.TestCase):
    def test_unknown_platform_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            accounts.accounts_file("mastodon")

    def test_add_normalizes_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                self.assertTrue(accounts.add("instagram", "@NASA"))
                self.assertFalse(accounts.add("instagram", "nasa"))
                self.assertEqual(accounts.list_accounts("instagram"), {"instagram": ["nasa"]})

    def test_remove_drops_only_the_matching_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                accounts.add("instagram", "nasa")
                accounts.add("instagram", "natgeo")

                self.assertTrue(accounts.remove("instagram", "@NASA"))
                self.assertEqual(accounts.list_accounts("instagram"), {"instagram": ["natgeo"]})

    def test_remove_missing_account_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                self.assertFalse(accounts.remove("instagram", "nasa"))

    def test_list_accounts_defaults_to_every_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                accounts.add("instagram", "nasa")
                accounts.add("tiktok", "khaby.lame")

                result = accounts.list_accounts()
                self.assertEqual(result["instagram"], ["nasa"])
                self.assertEqual(result["tiktok"], ["khaby.lame"])
                self.assertEqual(result["youtube"], [])

    def test_add_does_not_duplicate_a_hand_typed_mixed_case_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                path = accounts.accounts_file("youtube")
                path.parent.mkdir(parents=True)
                path.write_text("MrBeast\n", encoding="utf-8")

                self.assertFalse(accounts.add("youtube", "mrbeast"))
                self.assertEqual(path.read_text(encoding="utf-8"), "MrBeast\n")

    def test_remove_finds_a_hand_typed_mixed_case_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                path = accounts.accounts_file("youtube")
                path.parent.mkdir(parents=True)
                path.write_text("MrBeast\nveritasium\n", encoding="utf-8")

                self.assertTrue(accounts.remove("youtube", "mrbeast"))
                self.assertEqual(path.read_text(encoding="utf-8"), "veritasium\n")

    def test_add_rejects_empty_username(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            with patch.object(accounts.config, "CONFIG_DIR", config_dir):
                with self.assertRaises(SystemExit):
                    accounts.add("instagram", "  @ ")


if __name__ == "__main__":
    unittest.main()
