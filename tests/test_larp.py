from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import larp


class StyleStorageTests(unittest.TestCase):
    def test_add_read_remove_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                self.assertEqual(larp.read_templates("casual"), [])
                self.assertEqual(larp.list_styles(), [])

                larp.add_template("casual", "first template")
                larp.add_template("casual", "second\ntemplate")
                self.assertEqual(
                    larp.read_templates("casual"), ["first template", "second\ntemplate"]
                )
                self.assertEqual(larp.list_styles(), ["casual"])

                removed = larp.remove_template("casual", 0)
                self.assertEqual(removed, "first template")
                self.assertEqual(larp.read_templates("casual"), ["second\ntemplate"])

    def test_removing_last_template_drops_the_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "only one")
                larp.remove_template("casual", 0)
                self.assertEqual(larp.list_styles(), [])
                self.assertEqual(larp.read_templates("casual"), [])

    def test_styles_are_kept_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "casual one")
                larp.add_template("formal", "formal one")

                self.assertEqual(larp.list_styles(), ["casual", "formal"])
                self.assertEqual(larp.read_templates("casual"), ["casual one"])
                self.assertEqual(larp.read_templates("formal"), ["formal one"])

    def test_read_templates_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            styles_dir.mkdir(parents=True)
            (styles_dir / "casual.txt").write_text(
                "# a comment\n"
                "hello world\n"
                "\n"
                "# another comment\n"
                "second one\n",
                encoding="utf-8",
            )

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                self.assertEqual(larp.read_templates("casual"), ["hello world", "second one"])

    def test_remove_template_out_of_range_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "only one")
                with self.assertRaises(IndexError):
                    larp.remove_template("casual", 5)

    def test_add_template_rejects_invalid_style_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                with self.assertRaises(ValueError):
                    larp.add_template("../escape", "text")

    def test_rename_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "hello")
                larp.rename_style("casual", "chatty")
                self.assertEqual(larp.list_styles(), ["chatty"])
                self.assertEqual(larp.read_templates("chatty"), ["hello"])

    def test_rename_style_missing_source_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                with self.assertRaises(SystemExit):
                    larp.rename_style("missing", "new")

    def test_rename_style_existing_destination_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "hello")
                larp.add_template("formal", "hi")
                with self.assertRaises(SystemExit):
                    larp.rename_style("casual", "formal")

    def test_delete_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "hello")
                larp.delete_style("casual")
                self.assertEqual(larp.list_styles(), [])

    def test_delete_missing_style_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                with self.assertRaises(SystemExit):
                    larp.delete_style("missing")


class CorpusTests(unittest.TestCase):
    def test_build_corpus_returns_the_given_styles_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "saved template text")
                corpus = larp.build_corpus(style="casual")

            self.assertEqual(corpus, ["saved template text"])

    def test_build_corpus_auto_uses_the_only_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "only style template")
                corpus = larp.build_corpus()

            self.assertEqual(corpus, ["only style template"])

    def test_build_corpus_with_no_styles_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                self.assertEqual(larp.build_corpus(), [])

    def test_build_corpus_requires_style_when_multiple_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "one")
                larp.add_template("formal", "two")
                with self.assertRaises(SystemExit):
                    larp.build_corpus()

    def test_build_corpus_unknown_style_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"

            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "one")
                with self.assertRaises(SystemExit):
                    larp.build_corpus(style="nope")


class BuildPromptTests(unittest.TestCase):
    def test_includes_all_examples_and_instruction(self) -> None:
        prompt = larp._build_prompt(["first example", "second example"])
        self.assertIn("first example", prompt)
        self.assertIn("second example", prompt)
        self.assertIn("Example 1", prompt)
        self.assertIn("Example 2", prompt)
        self.assertIn("Do not copy", prompt)

    def test_no_language_given_has_no_language_instruction(self) -> None:
        prompt = larp._build_prompt(["example"])
        self.assertNotIn("Write it in", prompt)

    def test_language_given_adds_instruction(self) -> None:
        prompt = larp._build_prompt(["example"], language="Korean")
        self.assertIn("Write it in Korean", prompt)


class GenerateTests(unittest.TestCase):
    def test_missing_api_key_raises_before_any_llm_call(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(larp.llm.brain, "active_profile", return_value=None),
            patch.object(larp.llm, "call") as mock_call,
        ):
            with self.assertRaises(SystemExit) as ctx:
                larp.generate(style="casual")

        mock_call.assert_not_called()
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))

    def test_generate_without_corpus_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
            ):
                with self.assertRaises(SystemExit):
                    larp.generate()

    def test_generate_uses_corpus_and_calls_llm_count_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                results = larp.generate(style="casual", count=3)

            self.assertEqual(results, ["generated", "generated", "generated"])
            self.assertEqual(mock_call.call_count, 3)
            prompt = mock_call.call_args.args[0]
            self.assertIn("example one", prompt)

    def test_generate_passes_api_base_through_to_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            custom_base = "https://openrouter.ai/api/v1/chat/completions"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual", api_base=custom_base)

            self.assertEqual(mock_call.call_args.kwargs["api_base"], custom_base)

    def test_generate_defaults_max_tokens_to_llm_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual")

            self.assertEqual(mock_call.call_args.kwargs["max_tokens"], larp.llm.DEFAULT_MAX_TOKENS)

    def test_generate_passes_max_tokens_through_to_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual", max_tokens=1500)

            self.assertEqual(mock_call.call_args.kwargs["max_tokens"], 1500)

    def test_generate_passes_language_into_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual", language="Korean")

            prompt = mock_call.call_args.args[0]
            self.assertIn("Write it in Korean", prompt)

    def test_generate_caps_few_shot_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", return_value="generated") as mock_call,
            ):
                for i in range(10):
                    larp.add_template("casual", f"example number {i}")
                larp.generate(style="casual", max_examples=8)

            prompt = mock_call.call_args.args[0]
            self.assertIn("example number 0", prompt)
            self.assertIn("example number 7", prompt)
            self.assertNotIn("example number 8", prompt)
            self.assertNotIn("example number 9", prompt)

    def test_generate_requires_style_when_multiple_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
            ):
                larp.add_template("casual", "one")
                larp.add_template("formal", "two")
                with self.assertRaises(SystemExit):
                    larp.generate()

    def test_generate_converts_llm_error_to_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.llm.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.llm, "call", side_effect=larp.llm.LlmError("boom")),
            ):
                larp.add_template("casual", "one")
                with self.assertRaises(SystemExit) as ctx:
                    larp.generate(style="casual")
            self.assertIn("boom", str(ctx.exception))


class BrowseTests(unittest.TestCase):
    def test_no_saved_templates_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                with self.assertRaises(SystemExit):
                    larp.browse("casual")

    def test_quits_immediately_on_q(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.termui, "read_key", side_effect=["q"]),
            ):
                larp.add_template("casual", "one")
                larp.browse("casual")

    def test_right_advances_and_clamps_at_the_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(
                    larp.termui, "read_key", side_effect=["right", "right", "right", "q"]
                ) as mock_read_key,
            ):
                larp.add_template("casual", "one")
                larp.add_template("casual", "two")
                larp.browse("casual")

            self.assertEqual(mock_read_key.call_count, 4)

    def test_left_goes_back_and_clamps_at_the_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.termui, "read_key", side_effect=["left", "left", "q"]),
            ):
                larp.add_template("casual", "one")
                larp.add_template("casual", "two")
                larp.browse("casual")

    def test_enter_and_ctrl_c_and_esc_all_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "one")
                for quit_key in ("\r", "\n", "\x03", "esc"):
                    with patch.object(larp.termui, "read_key", side_effect=[quit_key]):
                        larp.browse("casual")

    @patch("builtins.print")
    def test_renders_the_current_template_text(self, mock_print) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp.termui, "read_key", side_effect=["right", "q"]),
            ):
                larp.add_template("casual", "first template")
                larp.add_template("casual", "second template")
                larp.browse("casual")

            printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("first template", printed)
            self.assertIn("second template", printed)


if __name__ == "__main__":
    unittest.main()
