from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from yunoballizer import llm


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class ResolveModelTests(unittest.TestCase):
    def test_explicit_model_wins(self) -> None:
        with patch.dict("os.environ", {llm.MODEL_ENV: "mistral"}):
            self.assertEqual(llm.resolve_model("llama-3.1-8b-instant"), "llama-3.1-8b-instant")

    def test_env_var_used_when_no_explicit_model(self) -> None:
        with patch.dict("os.environ", {llm.MODEL_ENV: "mistral"}):
            self.assertEqual(llm.resolve_model(None), "mistral")

    def test_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(llm.resolve_model(None), llm.DEFAULT_MODEL)


class ResolveApiBaseTests(unittest.TestCase):
    def test_explicit_api_base_wins(self) -> None:
        with patch.dict("os.environ", {llm.API_BASE_ENV: "https://env.example/v1/chat/completions"}):
            self.assertEqual(
                llm.resolve_api_base("https://explicit.example/v1/chat/completions"),
                "https://explicit.example/v1/chat/completions",
            )

    def test_env_var_used_when_no_explicit_api_base(self) -> None:
        with patch.dict("os.environ", {llm.API_BASE_ENV: "https://env.example/v1/chat/completions"}):
            self.assertEqual(llm.resolve_api_base(None), "https://env.example/v1/chat/completions")

    def test_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(llm.resolve_api_base(None), llm.DEFAULT_API_BASE)


class ResolveApiKeyTests(unittest.TestCase):
    def test_reads_the_configured_env_var(self) -> None:
        with patch.dict("os.environ", {llm.API_KEY_ENV: "test-key"}):
            self.assertEqual(llm.resolve_api_key(), "test-key")

    def test_missing_returns_none(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(llm.resolve_api_key())


class CallTests(unittest.TestCase):
    def test_sends_expected_request_and_parses_response(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "  hello world  \n"}}]})

        with patch.object(llm.urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            text = llm.call(
                "a prompt", api_key="test-key", model="llama-3.3-70b-versatile",
                api_base=llm.DEFAULT_API_BASE, timeout=5,
            )

        self.assertEqual(text, "hello world")
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, llm.DEFAULT_API_BASE)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "llama-3.3-70b-versatile")
        self.assertEqual(body["messages"], [{"role": "user", "content": "a prompt"}])

    def test_resolves_model_and_api_base_when_not_given(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "hi"}}]})

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(llm.urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen,
        ):
            llm.call("prompt", api_key="key")

        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, llm.DEFAULT_API_BASE)
        self.assertEqual(json.loads(request.data)["model"], llm.DEFAULT_MODEL)

    def test_sends_request_to_a_custom_api_base(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "hi"}}]})
        custom_base = "https://openrouter.ai/api/v1/chat/completions"

        with patch.object(llm.urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            llm.call("prompt", api_key="key", model="m", api_base=custom_base, timeout=5)

        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, custom_base)

    def test_401_at_default_api_base_mentions_groq(self) -> None:
        error = urllib.error.HTTPError(url=llm.DEFAULT_API_BASE, code=401, msg="Unauthorized", hdrs=None, fp=None)
        with patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.LlmError) as ctx:
                llm.call("prompt", api_key="bad", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))
        self.assertIn("console.groq.com", str(ctx.exception))

    def test_401_at_custom_api_base_does_not_mention_groq(self) -> None:
        custom_base = "https://openrouter.ai/api/v1/chat/completions"
        error = urllib.error.HTTPError(url=custom_base, code=401, msg="Unauthorized", hdrs=None, fp=None)
        with patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.LlmError) as ctx:
                llm.call("prompt", api_key="bad", model="m", api_base=custom_base, timeout=5)
        self.assertIn("YUNOBALLIZER_API_KEY", str(ctx.exception))
        self.assertNotIn("console.groq.com", str(ctx.exception))

    def test_429_raises_mentioning_rate_limit(self) -> None:
        error = urllib.error.HTTPError(url=llm.DEFAULT_API_BASE, code=429, msg="Too Many Requests", hdrs=None, fp=None)
        with patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.LlmError) as ctx:
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)
        self.assertIn("rate limit", str(ctx.exception).lower())

    def test_other_http_error_raises(self) -> None:
        error = urllib.error.HTTPError(url=llm.DEFAULT_API_BASE, code=500, msg="Server Error", hdrs=None, fp=None)
        with patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.LlmError):
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)

    def test_network_error_raises(self) -> None:
        error = urllib.error.URLError("no route to host")
        with patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.LlmError) as ctx:
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)
        self.assertIn("internet connection", str(ctx.exception).lower())

    def test_malformed_json_raises(self) -> None:
        resp = MagicMock()
        resp.read.return_value = b"not json"
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with patch.object(llm.urllib.request, "urlopen", return_value=resp):
            with self.assertRaises(llm.LlmError):
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)

    def test_missing_completion_field_raises(self) -> None:
        mock_resp = _mock_response({"choices": []})
        with patch.object(llm.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(llm.LlmError):
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)

    def test_empty_completion_raises(self) -> None:
        mock_resp = _mock_response({"choices": [{"message": {"content": "   "}}]})
        with patch.object(llm.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(llm.LlmError):
                llm.call("prompt", api_key="key", model="m", api_base=llm.DEFAULT_API_BASE, timeout=5)


if __name__ == "__main__":
    unittest.main()
