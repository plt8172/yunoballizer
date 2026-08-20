from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config, llm
from yunoballizer import cli
from yunoballizer.commands import select


class AutomaticSelectTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        downloaded = root / "downloaded"
        seed_dir = downloaded / "instagram" / "seed" / "one"
        candidate_dir = downloaded / "instagram" / "candidate" / "two"
        seed_dir.mkdir(parents=True)
        candidate_dir.mkdir(parents=True)
        seed = seed_dir / "image.jpg"
        candidate = candidate_dir / "video.mp4"
        seed.write_bytes(b"seed")
        candidate.write_bytes(b"candidate")
        (seed_dir / "caption.txt").write_text("street photography", encoding="utf-8")
        (candidate_dir / "caption.txt").write_text("night walk", encoding="utf-8")
        return downloaded, root / "config", root / "selected.json"

    def test_run_records_automatic_selections_in_selected_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            downloaded, config_dir, log_path = self._paths(root)
            rejected_dir = downloaded / "instagram" / "rejected" / "three"
            rejected_dir.mkdir(parents=True)
            rejected = rejected_dir / "image.jpg"
            rejected.write_bytes(b"rejected")
            (rejected_dir / "caption.txt").write_text(
                "generic product promotion", encoding="utf-8"
            )
            log_path.write_text(json.dumps({
                "instagram/seed/one/image.jpg": {
                    "status": "selected", "source": "manual", "decided_at": 1
                },
                "instagram/rejected/three/image.jpg": {
                    "status": "rejected", "source": "manual", "decided_at": 2
                }
            }), encoding="utf-8")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded),
                patch.object(config, "CONFIG_DIR", config_dir),
                patch.object(config, "SELECTED_PATH", log_path),
                patch.dict("os.environ", {llm.API_KEY_ENV: "key"}),
                patch.object(select.llm, "call", return_value="yes") as mock_call,
            ):
                select.run_auto()

            stored = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["instagram/seed/one/image.jpg"]["source"], "manual")
            self.assertEqual(stored["instagram/candidate/two/video.mp4"]["status"], "selected")
            self.assertEqual(stored["instagram/candidate/two/video.mp4"]["source"], "auto")
            prompt = mock_call.call_args.args[0]
            self.assertIn("Posts the user manually selected", prompt)
            self.assertIn("street photography", mock_call.call_args.args[0])
            self.assertIn("Posts the user manually rejected", prompt)
            self.assertIn("generic product promotion", prompt)
            self.assertIn("night walk", mock_call.call_args.args[0])

    def test_manual_rejection_is_not_reconsidered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            downloaded, config_dir, log_path = self._paths(root)
            log_path.write_text(json.dumps({
                "instagram/seed/one/image.jpg": {
                    "status": "selected", "source": "manual", "decided_at": 1
                },
                "instagram/candidate/two/video.mp4": {
                    "status": "rejected", "source": "manual", "decided_at": 2
                },
            }), encoding="utf-8")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded),
                patch.object(config, "CONFIG_DIR", config_dir),
                patch.object(config, "SELECTED_PATH", log_path),
                patch.dict("os.environ", {llm.API_KEY_ENV: "key"}),
                patch.object(select.llm, "call") as mock_call,
            ):
                select.run_auto()

            mock_call.assert_not_called()

    def test_any_existing_media_decision_skips_the_whole_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            downloaded = root / "downloaded"
            post_dir = downloaded / "instagram" / "acct" / "carousel"
            post_dir.mkdir(parents=True)
            first = post_dir / "image_01.jpg"
            second = post_dir / "image_02.jpg"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            log = {
                "instagram/acct/carousel/image_01.jpg": {
                    "status": "selected", "source": "manual", "decided_at": 1
                }
            }

            with patch.object(config, "DOWNLOADED_DIR", downloaded):
                pending = select._unreviewed_posts(log)

            self.assertEqual(pending, [])

    def test_missing_taste_signal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch.object(config, "DOWNLOADED_DIR", root / "downloaded"),
                patch.object(config, "CONFIG_DIR", root / "config"),
                patch.object(config, "SELECTED_PATH", root / "selected.json"),
                patch.dict("os.environ", {llm.API_KEY_ENV: "key"}),
                patch.object(
                    select.accounts_mod,
                    "list_accounts",
                    side_effect=AssertionError("automatic selection must not read account inputs"),
                ),
            ):
                with self.assertRaisesRegex(SystemExit, "taste signal"):
                    select.run_auto()

    def test_automatic_selections_are_not_reused_as_taste_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            downloaded, config_dir, log_path = self._paths(root)
            log_path.write_text(json.dumps({
                "instagram/seed/one/image.jpg": {
                    "status": "selected", "source": "auto", "decided_at": 1
                }
            }), encoding="utf-8")

            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded),
                patch.object(config, "CONFIG_DIR", config_dir),
                patch.object(config, "SELECTED_PATH", log_path),
                patch.dict("os.environ", {llm.API_KEY_ENV: "key"}),
            ):
                with self.assertRaisesRegex(SystemExit, "taste signal"):
                    select.run_auto()

    def test_missing_api_key_is_rejected(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(select.llm.brain, "active_profile", return_value=None),
        ):
            with self.assertRaisesRegex(SystemExit, "brain config"):
                select.run_auto()

    def test_select_auto_cli_accepts_limit(self) -> None:
        args = cli.build_parser().parse_args(["select", "--auto", "--limit", "5"])

        self.assertEqual(args.command, "select")
        self.assertTrue(args.auto)
        self.assertEqual(args.limit, 5)

    def test_select_defaults_to_manual_mode(self) -> None:
        args = cli.build_parser().parse_args(["select"])

        self.assertFalse(args.auto)
        self.assertIsNone(args.limit)

    def test_manual_select_rejects_auto_only_limit(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--limit requires --auto"):
            cli.main(["select", "--limit", "5"])

    def test_select_auto_defaults_to_twenty_posts(self) -> None:
        with patch.object(select, "run_auto") as run_auto:
            cli.main(["select", "--auto"])

        run_auto.assert_called_once_with(limit=20)


if __name__ == "__main__":
    unittest.main()
