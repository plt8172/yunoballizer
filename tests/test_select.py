from __future__ import annotations

import errno
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config, select


class RecordSelectionTests(unittest.TestCase):
    def test_adds_new_entries_and_skips_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir = root / "sources"
            (sources_dir / "instagram" / "acct" / "postid").mkdir(parents=True)
            media = sources_dir / "instagram" / "acct" / "postid" / "image_01.jpg"
            media.write_bytes(b"data")
            log_path = root / "state" / "selection_log.json"

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "SELECTION_LOG_PATH", log_path),
            ):
                added_first = select.record_selection([media])
                added_second = select.record_selection([media])

            self.assertEqual(added_first, 1)
            self.assertEqual(added_second, 0)
            self.assertTrue(log_path.exists())

    def test_skips_paths_outside_sources_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir = root / "sources"
            sources_dir.mkdir()
            outside = root / "elsewhere.jpg"
            outside.write_bytes(b"data")
            log_path = root / "state" / "selection_log.json"

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "SELECTION_LOG_PATH", log_path),
            ):
                added = select.record_selection([outside])

            self.assertEqual(added, 0)


class ExportTests(unittest.TestCase):
    def _setup(self, root: Path):
        sources_dir = root / "sources"
        selected_dir = root / "selected"
        post_dir = sources_dir / "instagram" / "acct" / "postid"
        post_dir.mkdir(parents=True)
        media = post_dir / "image_01.jpg"
        media.write_bytes(b"data")
        log_path = root / "state" / "selection_log.json"
        return sources_dir, selected_dir, media, log_path

    def test_hardlinks_selected_media_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir, selected_dir, media, log_path = self._setup(root)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "SELECTED_DIR", selected_dir),
                patch.object(config, "SELECTION_LOG_PATH", log_path),
            ):
                select.record_selection([media])
                exported_first = select.export()
                exported_second = select.export()

            files = list(selected_dir.iterdir())
            self.assertEqual(exported_first, 1)
            self.assertEqual(exported_second, 0)
            self.assertEqual(len(files), 1)
            self.assertFalse(files[0].is_symlink())
            self.assertEqual(files[0].read_bytes(), b"data")

    def test_falls_back_to_copy_across_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir, selected_dir, media, log_path = self._setup(root)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "SELECTED_DIR", selected_dir),
                patch.object(config, "SELECTION_LOG_PATH", log_path),
            ):
                select.record_selection([media])
                with patch("os.link", side_effect=OSError(errno.EXDEV, "cross-device link")):
                    exported = select.export()

            files = list(selected_dir.iterdir())
            self.assertEqual(exported, 1)
            self.assertEqual(len(files), 1)
            self.assertFalse(files[0].is_symlink())
            self.assertEqual(files[0].read_bytes(), b"data")

    def test_skips_missing_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir, selected_dir, media, log_path = self._setup(root)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "SELECTED_DIR", selected_dir),
                patch.object(config, "SELECTION_LOG_PATH", log_path),
            ):
                select.record_selection([media])
                media.unlink()
                exported = select.export()

            self.assertEqual(exported, 0)


class PickTests(unittest.TestCase):
    def test_returns_resolved_paths_from_viewer_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_file = root / "real.jpg"
            real_file.write_bytes(b"data")
            link = root / "link.jpg"
            link.symlink_to(real_file)

            fake_result = subprocess.CompletedProcess(
                args=["nsxiv"], returncode=0, stdout=f"{link}\n", stderr=""
            )
            with patch("subprocess.run", return_value=fake_result) as mock_run:
                marked = select.pick(source_dir=root)

            mock_run.assert_called_once()
            self.assertEqual(marked, [real_file.resolve()])

    def test_missing_viewer_binary_raises_system_exit(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(SystemExit):
                select.pick(source_dir=Path("/tmp"), viewer=["definitely-not-installed"])

    def test_viewer_error_raises_system_exit(self) -> None:
        error = subprocess.CalledProcessError(1, ["nsxiv"], stderr="boom")
        with patch("subprocess.run", side_effect=error):
            with self.assertRaises(SystemExit):
                select.pick(source_dir=Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
