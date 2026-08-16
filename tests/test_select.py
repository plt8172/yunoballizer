from __future__ import annotations

import errno
import os
import shutil
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
    def _review_dir_with_links(self, root: Path, count: int) -> tuple[Path, list[Path]]:
        review_dir = root / "review"
        review_dir.mkdir()
        real_files = []
        for i in range(count):
            real_file = root / f"real{i}.jpg"
            real_file.write_bytes(f"data{i}".encode())
            link = review_dir / f"link{i}.jpg"
            link.symlink_to(real_file)
            real_files.append(real_file.resolve())
        return review_dir, real_files

    def test_navigation_and_toggle_selects_the_right_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, real_files = self._review_dir_with_links(Path(tmpdir), 3)
            keys = iter(["right", "s", "right", "s", "left", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item"),
            ):
                marked = select.pick(source_dir=review_dir)

            self.assertEqual(set(marked), {real_files[1], real_files[2]})

    def test_toggling_the_same_item_twice_deselects_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _ = self._review_dir_with_links(Path(tmpdir), 2)
            keys = iter(["s", "s", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item"),
            ):
                marked = select.pick(source_dir=review_dir)

            self.assertEqual(marked, [])

    def test_index_clamps_at_bounds_instead_of_wrapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, real_files = self._review_dir_with_links(Path(tmpdir), 2)
            keys = iter(["right", "right", "right", "s", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item"),
            ):
                marked = select.pick(source_dir=review_dir)

            self.assertEqual(marked, [real_files[1]])

    def test_o_key_opens_current_item_natively(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, real_files = self._review_dir_with_links(Path(tmpdir), 2)
            keys = iter(["right", "o", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item"),
                patch.object(select, "open_native") as mock_open,
            ):
                select.pick(source_dir=review_dir)

            mock_open.assert_called_once()
            self.assertEqual(mock_open.call_args[0][0].resolve(), real_files[1])

    def test_empty_review_dir_returns_immediately_without_reading_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir = Path(tmpdir) / "review"
            review_dir.mkdir()

            with (
                patch.object(select, "_read_key") as mock_read_key,
                patch.object(select, "_render_item") as mock_render,
            ):
                marked = select.pick(source_dir=review_dir)

            mock_read_key.assert_not_called()
            mock_render.assert_not_called()
            self.assertEqual(marked, [])

    def test_unbound_keys_cause_no_redraw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _ = self._review_dir_with_links(Path(tmpdir), 2)
            # "x", "z", and a stray escape sequence are not bound to anything.
            keys = iter(["x", "z", "esc", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item") as mock_render,
            ):
                select.pick(source_dir=review_dir)

            # Only the initial render before the loop starts -- none of the
            # unbound keys should trigger another one.
            mock_render.assert_called_once()

    def test_clamped_movement_does_not_redraw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir, _ = self._review_dir_with_links(Path(tmpdir), 2)
            # Already at index 0; "left" can't move further, so no redraw.
            keys = iter(["left", "left", "q"])

            with (
                patch.object(select, "_read_key", side_effect=keys),
                patch.object(select, "_render_item") as mock_render,
            ):
                select.pick(source_dir=review_dir)

            mock_render.assert_called_once()


class DescribeTests(unittest.TestCase):
    def test_splits_platform_account_post_id_and_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir = Path(tmpdir) / "sources"
            post_dir = sources_dir / "instagram" / "nasa" / "ShortcodeA"
            post_dir.mkdir(parents=True)
            media = post_dir / "image_02.jpg"
            media.write_bytes(b"data")

            with patch.object(config, "SOURCES_DIR", sources_dir):
                platform, account, post_id, filename = select._describe(media)

            self.assertEqual((platform, account, post_id, filename),
                              ("instagram", "nasa", "ShortcodeA", "image_02.jpg"))

    def test_falls_back_to_bare_filename_outside_sources_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir = Path(tmpdir) / "sources"
            sources_dir.mkdir()
            outside = Path(tmpdir) / "elsewhere.jpg"
            outside.write_bytes(b"data")

            with patch.object(config, "SOURCES_DIR", sources_dir):
                platform, account, post_id, filename = select._describe(outside)

            self.assertEqual((platform, account, post_id), ("", "", ""))
            self.assertEqual(filename, "elsewhere.jpg")


class RenderItemTests(unittest.TestCase):
    def test_resolves_symlink_before_looking_up_caption(self) -> None:
        """Regression test: find_caption() needs the real sources/ post
        directory, not review/'s flat symlink directory, or captions never
        show up even when caption.txt exists right next to the media."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir = root / "sources"
            review_dir = root / "review"
            review_dir.mkdir()
            post_dir = sources_dir / "instagram" / "nasa" / "ShortcodeA"
            post_dir.mkdir(parents=True)
            media = post_dir / "image_01.jpg"
            media.write_bytes(b"data")
            (post_dir / "caption.txt").write_text("hello world", encoding="utf-8")
            link = review_dir / "link.jpg"
            link.symlink_to(media)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(select, "render_preview"),
                patch("builtins.print") as mock_print,
            ):
                select._render_item(link, 0, 1, set())

            printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("hello world", printed)

    def _item(self, root: Path, caption: str | None) -> tuple[Path, Path]:
        sources_dir = root / "sources"
        post_dir = sources_dir / "instagram" / "nasa" / "ShortcodeA"
        post_dir.mkdir(parents=True)
        media = post_dir / "image_01.jpg"
        media.write_bytes(b"data")
        if caption is not None:
            (post_dir / "caption.txt").write_text(caption, encoding="utf-8")
        return sources_dir, media

    def test_image_height_budget_never_exceeds_terminal_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir, media = self._item(Path(tmpdir), caption=None)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 40))),
                patch.object(select, "render_preview") as mock_preview,
                patch("builtins.print"),
            ):
                select._render_item(media, 0, 1, set())

            height = mock_preview.call_args.kwargs["height"]
            # header + blank + blank + footer = 4 fixed rows, no caption here.
            self.assertEqual(height, 40 - 4)

    def test_image_height_budget_accounts_for_caption_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir, media = self._item(Path(tmpdir), caption="a short caption")

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 40))),
                patch.object(select, "render_preview") as mock_preview,
                patch("builtins.print"),
            ):
                select._render_item(media, 0, 1, set())

            height = mock_preview.call_args.kwargs["height"]
            # 4 fixed rows + caption line + its trailing blank line.
            self.assertEqual(height, 40 - 6)

    def test_long_caption_is_truncated_to_a_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_dir, media = self._item(Path(tmpdir), caption="x" * 500)

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch("shutil.get_terminal_size", return_value=os.terminal_size((60, 40))),
                patch.object(select, "render_preview"),
                patch("builtins.print") as mock_print,
            ):
                select._render_item(media, 0, 1, set())

            caption_lines = [c.args[0] for c in mock_print.call_args_list if c.args and "x" in str(c.args[0])]
            self.assertEqual(len(caption_lines), 1)
            self.assertLess(len(caption_lines[0]), 60)


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
            self.assertEqual(args[1], "-h")
            self.assertEqual(args[-1], str(image))

    def test_explicit_height_is_used_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = Path(tmpdir) / "photo.jpg"
            image.write_bytes(b"data")

            with patch("subprocess.run") as mock_run:
                select.render_preview(image, height=17)

            args = mock_run.call_args[0][0]
            self.assertEqual(args[2], "17")

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
