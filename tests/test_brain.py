from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer.commands import brain


class BrainProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        config_dir = Path(self._tmpdir.name)
        patcher = patch.object(brain.config, "CONFIG_DIR", config_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _configure(self, name: str, api_key: str, model: str = "", api_base: str = "") -> None:
        with (
            patch.object(brain.getpass, "getpass", return_value=api_key),
            patch("builtins.input", side_effect=[model, api_base]),
        ):
            brain.configure(name)

    def test_save_and_read_round_trip(self) -> None:
        brain.save_profile("groq", "gsk_123", model="llama-3.1-8b-instant")

        self.assertEqual(
            brain.read_profile("groq"),
            {"api_key": "gsk_123", "model": "llama-3.1-8b-instant"},
        )
        self.assertEqual(brain.saved_profiles(), ["groq"])
        self.assertEqual(brain.active_profile_name(), "groq")
        self.assertEqual(brain.active_profile(), brain.read_profile("groq"))

    def test_save_without_api_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            brain.save_profile("groq", "")

    def test_configure_saves_and_activates(self) -> None:
        self._configure("groq", "gsk_123")

        self.assertEqual(brain.read_profile("groq"), {"api_key": "gsk_123"})
        self.assertEqual(brain.active_profile_name(), "groq")

    def test_configure_blank_key_raises_without_saving(self) -> None:
        with (
            patch.object(brain.getpass, "getpass", return_value="  "),
            patch("builtins.input", side_effect=["", ""]),
        ):
            with self.assertRaises(SystemExit):
                brain.configure("groq")

        self.assertEqual(brain.saved_profiles(), [])

    def test_configure_blank_model_and_api_base_are_omitted(self) -> None:
        self._configure("groq", "gsk_123", model="", api_base="")

        self.assertEqual(brain.read_profile("groq"), {"api_key": "gsk_123"})

    def test_configure_includes_model_and_api_base_when_given(self) -> None:
        self._configure(
            "openrouter", "sk_456",
            model="gpt-oss", api_base="https://openrouter.ai/api/v1/chat/completions",
        )

        self.assertEqual(
            brain.read_profile("openrouter"),
            {
                "api_key": "sk_456",
                "model": "gpt-oss",
                "api_base": "https://openrouter.ai/api/v1/chat/completions",
            },
        )

    def test_saved_profiles_and_active_profile_name_empty_by_default(self) -> None:
        self.assertEqual(brain.saved_profiles(), [])
        self.assertIsNone(brain.active_profile_name())
        self.assertIsNone(brain.active_profile())
        self.assertIsNone(brain.read_profile("missing"))

    def test_second_configure_adds_profile_and_switches_active(self) -> None:
        self._configure("groq", "gsk_123")
        self._configure("openrouter", "sk_456")

        self.assertEqual(brain.saved_profiles(), ["groq", "openrouter"])
        self.assertEqual(brain.active_profile_name(), "openrouter")

    def test_permissions_are_restrictive(self) -> None:
        self._configure("groq", "gsk_123")

        profile_mode = stat.S_IMODE(brain._profile_file("groq").stat().st_mode)
        dir_mode = stat.S_IMODE(brain._profiles_dir().stat().st_mode)
        active_mode = stat.S_IMODE(brain._active_file().stat().st_mode)

        self.assertEqual(
            brain._active_file(),
            brain.config.CONFIG_DIR / "brain" / "profiles" / "active",
        )
        self.assertEqual(profile_mode, 0o600)
        self.assertEqual(dir_mode, 0o700)
        self.assertEqual(active_mode, 0o600)

    def test_switch_updates_active_profile(self) -> None:
        self._configure("groq", "gsk_123")
        self._configure("openrouter", "sk_456")

        brain.switch("groq")

        self.assertEqual(brain.active_profile_name(), "groq")

    def test_switch_unknown_name_raises(self) -> None:
        self._configure("groq", "gsk_123")

        with self.assertRaises(SystemExit):
            brain.switch("nobody")

    def test_switch_with_no_argument_cycles_to_next_profile(self) -> None:
        self._configure("alice", "k1")
        self._configure("bob", "k2")
        self._configure("carol", "k3")
        brain.switch("alice")  # sorted order: alice, bob, carol -- currently alice

        brain.switch()

        self.assertEqual(brain.active_profile_name(), "bob")

    def test_switch_with_no_argument_wraps_around(self) -> None:
        self._configure("alice", "k1")
        self._configure("bob", "k2")
        brain.switch("bob")  # last in sorted order

        brain.switch()

        self.assertEqual(brain.active_profile_name(), "alice")

    def test_switch_with_no_argument_and_only_one_profile_raises(self) -> None:
        self._configure("alice", "k1")

        with self.assertRaises(SystemExit):
            brain.switch()

    def test_switch_with_no_argument_and_no_profiles_raises(self) -> None:
        with self.assertRaises(SystemExit):
            brain.switch()

    def test_remove_active_profile_clears_active(self) -> None:
        self._configure("groq", "gsk_123")

        brain.remove_profile("groq")

        self.assertEqual(brain.saved_profiles(), [])
        self.assertIsNone(brain.active_profile_name())

    def test_remove_inactive_profile_keeps_active(self) -> None:
        self._configure("groq", "gsk_123")
        self._configure("openrouter", "sk_456")

        brain.remove_profile("groq")

        self.assertEqual(brain.saved_profiles(), ["openrouter"])
        self.assertEqual(brain.active_profile_name(), "openrouter")

    def test_remove_missing_profile_raises(self) -> None:
        with self.assertRaises(SystemExit):
            brain.remove_profile("nobody")

    def test_describe_active_with_no_profile(self) -> None:
        self.assertIn("No active brain profile", brain.describe_active())

    def test_describe_active_shows_model_and_endpoint(self) -> None:
        self._configure("groq", "gsk_123", model="llama-3.1-8b-instant")

        description = brain.describe_active()

        self.assertIn("groq", description)
        self.assertIn("llama-3.1-8b-instant", description)
        self.assertIn("(provider default)", description)  # api_base wasn't set

    def test_describe_unset_fields_show_provider_default(self) -> None:
        self._configure("groq", "gsk_123")

        description = brain.describe("groq")

        self.assertIn("(provider default)", description)


if __name__ == "__main__":
    unittest.main()
