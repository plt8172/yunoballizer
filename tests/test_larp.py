from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from yunoballizer import larp


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


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

    def test_get_template_returns_full_content_without_removing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "first template")
                larp.add_template("casual", "second\ntemplate")

                self.assertEqual(larp.get_template("casual", 1), "second\ntemplate")
                self.assertEqual(
                    larp.read_templates("casual"), ["first template", "second\ntemplate"]
                )

    def test_get_template_out_of_range_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with patch.object(larp.config, "LARP_STYLES_DIR", styles_dir):
                larp.add_template("casual", "only one")
                with self.assertRaises(IndexError):
                    larp.get_template("casual", 5)

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


class ResolveModelTests(unittest.TestCase):
    def test_explicit_model_wins(self) -> None:
        with patch.dict("os.environ", {larp.MODEL_ENV: "mistral"}):
            self.assertEqual(larp._resolve_model("llama-3.1-8b-instant"), "llama-3.1-8b-instant")

    def test_env_var_used_when_no_explicit_model(self) -> None:
        with patch.dict("os.environ", {larp.MODEL_ENV: "mistral"}):
            self.assertEqual(larp._resolve_model(None), "mistral")

    def test_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(larp._resolve_model(None), larp.DEFAULT_MODEL)


class ResolveApiBaseTests(unittest.TestCase):
    def test_explicit_api_base_wins(self) -> None:
        with patch.dict("os.environ", {larp.API_BASE_ENV: "https://env.example/v1/chat/completions"}):
            self.assertEqual(
                larp._resolve_api_base("https://explicit.example/v1/chat/completions"),
                "https://explicit.example/v1/chat/completions",
            )

    def test_env_var_used_when_no_explicit_api_base(self) -> None:
        with patch.dict("os.environ", {larp.API_BASE_ENV: "https://env.example/v1/chat/completions"}):
            self.assertEqual(larp._resolve_api_base(None), "https://env.example/v1/chat/completions")

    def test_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(larp._resolve_api_base(None), larp.DEFAULT_API_BASE)


class CallLlmTests(unittest.TestCase):
    def test_sends_expected_request_and_parses_response(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "  hello world  \n"}}]})

        with patch.object(larp.urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            text = larp._call_llm(
                "a prompt", api_key="test-key", model="llama-3.3-70b-versatile",
                api_base=larp.DEFAULT_API_BASE, timeout=5,
            )

        self.assertEqual(text, "hello world")
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, larp.DEFAULT_API_BASE)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "llama-3.3-70b-versatile")
        self.assertEqual(body["messages"], [{"role": "user", "content": "a prompt"}])

    def test_sends_request_to_a_custom_api_base(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "hi"}}]})
        custom_base = "https://openrouter.ai/api/v1/chat/completions"

        with patch.object(larp.urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            larp._call_llm("prompt", api_key="key", model="m", api_base=custom_base, timeout=5)

        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, custom_base)

    def test_401_at_default_api_base_mentions_groq(self) -> None:
        error = urllib.error.HTTPError(url=larp.DEFAULT_API_BASE, code=401, msg="Unauthorized", hdrs=None, fp=None)
        with patch.object(larp.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                larp._call_llm("prompt", api_key="bad", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))
        self.assertIn("console.groq.com", str(ctx.exception))

    def test_401_at_custom_api_base_does_not_mention_groq(self) -> None:
        custom_base = "https://openrouter.ai/api/v1/chat/completions"
        error = urllib.error.HTTPError(url=custom_base, code=401, msg="Unauthorized", hdrs=None, fp=None)
        with patch.object(larp.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                larp._call_llm("prompt", api_key="bad", model="m", api_base=custom_base, timeout=5)
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))
        self.assertNotIn("console.groq.com", str(ctx.exception))

    def test_429_raises_system_exit_mentioning_rate_limit(self) -> None:
        error = urllib.error.HTTPError(url=larp.DEFAULT_API_BASE, code=429, msg="Too Many Requests", hdrs=None, fp=None)
        with patch.object(larp.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)
        self.assertIn("rate limit", str(ctx.exception).lower())

    def test_other_http_error_raises_system_exit(self) -> None:
        error = urllib.error.HTTPError(url=larp.DEFAULT_API_BASE, code=500, msg="Server Error", hdrs=None, fp=None)
        with patch.object(larp.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit):
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)

    def test_network_error_raises_system_exit(self) -> None:
        error = urllib.error.URLError("no route to host")
        with patch.object(larp.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)
        self.assertIn("internet connection", str(ctx.exception).lower())

    def test_malformed_json_raises_system_exit(self) -> None:
        resp = MagicMock()
        resp.read.return_value = b"not json"
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with patch.object(larp.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(SystemExit):
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)

    def test_missing_completion_field_raises_system_exit(self) -> None:
        mock_resp = _mock_response({"choices": []})
        with patch.object(larp.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(SystemExit):
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)

    def test_empty_completion_raises_system_exit(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "   "}}]})
        with patch.object(larp.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(SystemExit):
                larp._call_llm("prompt", api_key="key", model="m", api_base=larp.DEFAULT_API_BASE, timeout=5)


class GenerateTests(unittest.TestCase):
    def test_missing_api_key_raises_before_any_http_call(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(larp, "_call_llm") as mock_call,
        ):
            with self.assertRaises(SystemExit) as ctx:
                larp.generate(style="casual")

        mock_call.assert_not_called()
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))

    def test_generate_without_corpus_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
            ):
                with self.assertRaises(SystemExit):
                    larp.generate()

    def test_generate_uses_corpus_and_calls_llm_count_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp, "_call_llm", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                results = larp.generate(style="casual", count=3)

            self.assertEqual(results, ["generated", "generated", "generated"])
            self.assertEqual(mock_call.call_count, 3)
            prompt = mock_call.call_args.args[0]
            self.assertIn("example one", prompt)

    def test_generate_passes_api_base_through_to_call_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            custom_base = "https://openrouter.ai/api/v1/chat/completions"
            with (
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp, "_call_llm", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual", api_base=custom_base)

            self.assertEqual(mock_call.call_args.kwargs["api_base"], custom_base)

    def test_generate_passes_language_into_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp, "_call_llm", return_value="generated") as mock_call,
            ):
                larp.add_template("casual", "example one")
                larp.generate(style="casual", language="Korean")

            prompt = mock_call.call_args.args[0]
            self.assertIn("Write it in Korean", prompt)

    def test_generate_caps_few_shot_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            styles_dir = Path(tmpdir) / "larp" / "styles"
            with (
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
                patch.object(larp, "_call_llm", return_value="generated") as mock_call,
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
                patch.dict("os.environ", {larp.API_KEY_ENV: "test-key"}),
                patch.object(larp.config, "LARP_STYLES_DIR", styles_dir),
            ):
                larp.add_template("casual", "one")
                larp.add_template("formal", "two")
                with self.assertRaises(SystemExit):
                    larp.generate()


if __name__ == "__main__":
    unittest.main()
