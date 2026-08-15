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
    def _review_dir_with_link(self, root: Path) -> tuple[Path, Path, Path]:
        review_dir = root / "review"
        review_dir.mkdir()
        real_file = root / "real.jpg"
        real_file.write_bytes(b"data")
        link = review_dir / "link.jpg"
        link.symlink_to(real_file)
        return review_dir, real_file, link

    def test_feeds_file_list_to_fzf_and_returns_resolved_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            review_dir, real_file, link = self._review_dir_with_link(root)

            fake_result = subprocess.CompletedProcess(
                args=["fzf"], returncode=0, stdout=f"{link}\n", stderr=""
            )
            with patch("subprocess.run", return_value=fake_result) as mock_run:
                marked = select.pick(source_dir=review_dir)

            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs["input"], str(link))
            self.assertEqual(marked, [real_file.resolve()])

    def test_empty_review_dir_skips_fzf_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir = Path(tmpdir) / "review"
            review_dir.mkdir()
            with patch("subprocess.run") as mock_run:
                marked = select.pick(source_dir=review_dir)

            mock_run.assert_not_called()
            self.assertEqual(marked, [])

    def test_missing_fzf_binary_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _, _ = self._review_dir_with_link(Path(tmpdir))
            with patch("subprocess.run", side_effect=FileNotFoundError):
                with self.assertRaises(SystemExit):
                    select.pick(source_dir=review_dir)

    def test_cancelled_fzf_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _, _ = self._review_dir_with_link(Path(tmpdir))
            fake_result = subprocess.CompletedProcess(
                args=["fzf"], returncode=select.FZF_CANCELLED, stdout="", stderr=""
            )
            with patch("subprocess.run", return_value=fake_result):
                marked = select.pick(source_dir=review_dir)

            self.assertEqual(marked, [])

    def test_fzf_error_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _, _ = self._review_dir_with_link(Path(tmpdir))
            fake_result = subprocess.CompletedProcess(
                args=["fzf"], returncode=2, stdout="", stderr="boom"
            )
            with patch("subprocess.run", return_value=fake_result):
                with self.assertRaises(SystemExit):
                    select.pick(source_dir=review_dir)


class RenderPreviewTests(unittest.TestCase):
    def test_image_is_previewed_directly_with_viu(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = Path(tmpdir) / "photo.jpg"
            image.write_bytes(b"data")

            with patch("subprocess.run") as mock_run:
                select.render_preview(image)

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "viu")
            self.assertEqual(args[-1], str(image))

    def test_video_extracts_frame_with_ffmpeg_then_previews_with_viu(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "clip.mp4"
            video.write_bytes(b"data")

            calls = []

            def fake_run(cmd, *args, **kwargs):
                calls.append(cmd)
                if cmd[0] == "ffmpeg":
                    Path(cmd[-1]).write_bytes(b"frame")
                    return subprocess.CompletedProcess(cmd, 0)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("subprocess.run", side_effect=fake_run):
                select.render_preview(video)

            self.assertEqual(calls[0][0], "ffmpeg")
            self.assertEqual(calls[1][0], "viu")
            self.assertNotEqual(calls[1][-1], str(video))

    def test_missing_ffmpeg_degrades_to_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "clip.mp4"
            video.write_bytes(b"data")

            with patch("subprocess.run", side_effect=FileNotFoundError):
                select.render_preview(video)  # must not raise

    def test_missing_viu_degrades_to_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = Path(tmpdir) / "photo.jpg"
            image.write_bytes(b"data")

            with patch("subprocess.run", side_effect=FileNotFoundError):
                select.render_preview(image)  # must not raise

    def test_missing_path_does_not_raise(self) -> None:
        select.render_preview(Path("/nonexistent/path.jpg"))


class OpenNativeTests(unittest.TestCase):
    def test_macos_uses_open(self) -> None:
        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            select.open_native(Path("/tmp/photo.jpg"))
            mock_run.assert_called_once_with(["open", "/tmp/photo.jpg"])

    def test_windows_uses_os_startfile(self) -> None:
        with patch("sys.platform", "win32"), patch("os.startfile", create=True) as mock_startfile:
            select.open_native(Path("C:/photo.jpg"))
            mock_startfile.assert_called_once_with("C:/photo.jpg")

    def test_linux_uses_xdg_open(self) -> None:
        with patch("sys.platform", "linux"), patch("subprocess.run") as mock_run:
            select.open_native(Path("/tmp/photo.jpg"))
            mock_run.assert_called_once_with(["xdg-open", "/tmp/photo.jpg"])


if __name__ == "__main__":
    unittest.main()
