from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yunoballizer import config, llm
from yunoballizer.commands import curate


class CurateRunTests(unittest.TestCase):
    def test_run_copies_kept_media_with_collision_safe_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_dir = root / "sources"
            curated_dir = root / "curated"
            derived_dir = root / "derived"
            state_dir = root / "state"

            for account in ("one", "two"):
                post_dir = sources_dir / "instagram" / account / "postid"
                post_dir.mkdir(parents=True)
                (post_dir / "video.mp4").write_bytes(b"data")
                (post_dir / "caption.txt").write_text("#seoul night walk", encoding="utf-8")

            profile_path = derived_dir / "taste_profile.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(
                json.dumps({"top_hashtags": ["seoul"], "top_keywords": ["night"]}),
                encoding="utf-8",
            )

            with (
                patch.object(config, "SOURCES_DIR", sources_dir),
                patch.object(config, "CURATED_DIR", curated_dir),
                patch.object(config, "DERIVED_DIR", derived_dir),
                patch.object(config, "CURATION_LOG_PATH", state_dir / "curation_log.json"),
            ):
                curate.run()

            curated_files = sorted(curated_dir.iterdir())
            self.assertEqual(len(curated_files), 2)
            self.assertEqual(len({p.name for p in curated_files}), 2)


class AskLlmTests(unittest.TestCase):
    def test_missing_api_key_warns_and_skips_without_calling_llm(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(curate.llm.brain, "active_profile", return_value=None),
            patch.object(curate.llm, "call") as mock_call,
        ):
            result = curate._ask_llm("some caption", {"top_hashtags": [], "top_keywords": []})

        self.assertFalse(result)
        mock_call.assert_not_called()

    def test_llm_error_is_caught_and_returns_false(self) -> None:
        with (
            patch.dict("os.environ", {llm.API_KEY_ENV: "test-key"}),
            patch.object(curate.llm, "call", side_effect=llm.LlmError("boom")),
        ):
            result = curate._ask_llm("some caption", {"top_hashtags": [], "top_keywords": []})

        self.assertFalse(result)

    def test_yes_answer_returns_true(self) -> None:
        with (
            patch.dict("os.environ", {llm.API_KEY_ENV: "test-key"}),
            patch.object(curate.llm, "call", return_value="Yes."),
        ):
            result = curate._ask_llm("some caption", {"top_hashtags": [], "top_keywords": []})

        self.assertTrue(result)

    def test_no_answer_returns_false(self) -> None:
        with (
            patch.dict("os.environ", {llm.API_KEY_ENV: "test-key"}),
            patch.object(curate.llm, "call", return_value="no"),
        ):
            result = curate._ask_llm("some caption", {"top_hashtags": [], "top_keywords": []})

        self.assertFalse(result)

    def test_prompt_includes_profile_signals_and_caption(self) -> None:
        with (
            patch.dict("os.environ", {llm.API_KEY_ENV: "test-key"}),
            patch.object(curate.llm, "call", return_value="yes") as mock_call,
        ):
            curate._ask_llm(
                "a caption about seoul",
                {"top_hashtags": ["seoul"], "top_keywords": ["night"]},
            )

        prompt = mock_call.call_args.args[0]
        self.assertIn("seoul", prompt)
        self.assertIn("night", prompt)
        self.assertIn("a caption about seoul", prompt)


if __name__ == "__main__":
    unittest.main()
