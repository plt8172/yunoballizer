from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config

_RELEVANT_ENV_VARS = ("YUNOBALLIZER_DATA_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME")


def _env(**overrides: str) -> dict[str, str]:
    """All relevant env vars explicitly unset (empty), except the given overrides."""
    env = {name: "" for name in _RELEVANT_ENV_VARS}
    env.update(overrides)
    return env


class XdgPathTests(unittest.TestCase):
    def test_data_root_prefers_explicit_override_over_xdg_over_default(self) -> None:
        with patch.dict("os.environ", _env(YUNOBALLIZER_DATA_DIR="/override", XDG_DATA_HOME="/xdg-data")):
            self.assertEqual(config._data_root(), Path("/override"))

        with patch.dict("os.environ", _env(XDG_DATA_HOME="/xdg-data")):
            self.assertEqual(config._data_root(), Path("/xdg-data") / "yunoballizer")

        with patch.dict("os.environ", _env()):
            self.assertEqual(config._data_root(), Path.home() / ".local" / "share" / "yunoballizer")

    def test_config_root_prefers_xdg_over_default(self) -> None:
        with patch.dict("os.environ", _env(XDG_CONFIG_HOME="/xdg-config")):
            self.assertEqual(config._config_root(), Path("/xdg-config") / "yunoballizer")

        with patch.dict("os.environ", _env()):
            self.assertEqual(config._config_root(), Path.home() / ".config" / "yunoballizer")

    def test_state_root_prefers_xdg_over_default(self) -> None:
        with patch.dict("os.environ", _env(XDG_STATE_HOME="/xdg-state")):
            self.assertEqual(config._state_root(), Path("/xdg-state") / "yunoballizer")

        with patch.dict("os.environ", _env()):
            self.assertEqual(config._state_root(), Path.home() / ".local" / "state" / "yunoballizer")

    def test_relative_paths_are_rejected_for_every_recognized_env_var(self) -> None:
        for name, resolver in (
            ("YUNOBALLIZER_DATA_DIR", config._data_root),
            ("XDG_DATA_HOME", config._data_root),
            ("XDG_CONFIG_HOME", config._config_root),
            ("XDG_STATE_HOME", config._state_root),
        ):
            with patch.dict("os.environ", _env(**{name: "relative/path"})):
                with self.assertRaises(SystemExit):
                    resolver()

    def test_empty_env_var_is_treated_as_unset(self) -> None:
        with patch.dict("os.environ", _env(XDG_DATA_HOME="")):
            self.assertEqual(config._data_root(), Path.home() / ".local" / "share" / "yunoballizer")


class EnsureConfigTests(unittest.TestCase):
    def test_ensure_config_creates_layout_and_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            config_dir = root / "config"
            state_dir = root / "state"

            with (
                patch.object(config, "DATA_DIR", data_dir),
                patch.object(config, "CONFIG_DIR", config_dir),
                patch.object(config, "STATE_DIR", state_dir),
                patch.object(config, "SOURCES_DIR", data_dir / "sources"),
                patch.object(config, "REVIEW_DIR", data_dir / "review"),
                patch.object(config, "CURATED_DIR", data_dir / "curated"),
                patch.object(config, "DERIVED_DIR", data_dir / "derived"),
                patch.object(config, "SELECTED_DIR", data_dir / "selected"),
                patch.object(config, "ARCHIVE_DIR", state_dir / "archives"),
                patch.object(config, "LOG_DIR", state_dir / "logs"),
                patch.object(config, "CURATION_LOG_PATH", state_dir / "curation_log.json"),
                patch.object(config, "LARP_STYLES_DIR", config_dir / "larp" / "styles"),
            ):
                config.ensure_config()

            self.assertTrue((data_dir / "sources").is_dir())
            self.assertTrue((data_dir / "review").is_dir())
            self.assertTrue((data_dir / "curated").is_dir())
            self.assertTrue((data_dir / "derived").is_dir())
            self.assertTrue((data_dir / "selected").is_dir())
            self.assertTrue((state_dir / "archives").is_dir())
            self.assertTrue((state_dir / "logs").is_dir())
            self.assertTrue((config_dir / "larp" / "styles").is_dir())
            self.assertTrue((config_dir / "instagram" / "accounts.txt").exists())
            self.assertTrue((config_dir / "youtube" / "accounts.txt").exists())
            self.assertTrue((config_dir / "tiktok" / "accounts.txt").exists())
            self.assertTrue((config_dir / "urls.txt").exists())
            self.assertFalse((config_dir / "youtube" / "hashtags.txt").exists())


class LoadEnvFileTests(unittest.TestCase):
    def test_loads_key_value_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")

            with (
                patch.object(config, "ENV_FILE", env_path),
                patch.dict("os.environ", {}, clear=True),
            ):
                config.load_env_file()
                self.assertEqual(os.environ.get("FOO"), "bar")
                self.assertEqual(os.environ.get("BAZ"), "qux")

    def test_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("# a comment\n\nFOO=bar\n# FOO=ignored\n", encoding="utf-8")

            with (
                patch.object(config, "ENV_FILE", env_path),
                patch.dict("os.environ", {}, clear=True),
            ):
                config.load_env_file()
                self.assertEqual(os.environ.get("FOO"), "bar")

    def test_strips_matching_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text('FOO="bar baz"\nQUX=\'quux\'\n', encoding="utf-8")

            with (
                patch.object(config, "ENV_FILE", env_path),
                patch.dict("os.environ", {}, clear=True),
            ):
                config.load_env_file()
                self.assertEqual(os.environ.get("FOO"), "bar baz")
                self.assertEqual(os.environ.get("QUX"), "quux")

    def test_does_not_override_an_existing_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("FOO=from_file\n", encoding="utf-8")

            with (
                patch.object(config, "ENV_FILE", env_path),
                patch.dict("os.environ", {"FOO": "from_shell"}),
            ):
                config.load_env_file()
                self.assertEqual(os.environ.get("FOO"), "from_shell")

    def test_missing_file_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            with patch.object(config, "ENV_FILE", env_path):
                config.load_env_file()  # must not raise


if __name__ == "__main__":
    unittest.main()
