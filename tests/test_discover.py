from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yunoballizer import config
from yunoballizer.commands import discover


class DiscoverTests(unittest.TestCase):
    def _selected_post(self, root: Path) -> tuple[Path, Path]:
        downloaded = root / "downloaded"
        post_dir = downloaded / "instagram" / "seed" / "post"
        post_dir.mkdir(parents=True)
        media = post_dir / "image.jpg"
        media.write_bytes(b"image")
        (post_dir / "caption.txt").write_text("hello @Alpha and @alpha", encoding="utf-8")
        log_path = root / "selected.json"
        log_path.write_text(json.dumps({
            "instagram/seed/post/image.jpg": {
                "status": "selected", "source": "manual", "decided_at": 1
            }
        }), encoding="utf-8")
        return downloaded, log_path

    def test_mentions_are_candidates_only_from_selected_posts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            downloaded, log_path = self._selected_post(root)
            with (
                patch.object(config, "DOWNLOADED_DIR", downloaded),
                patch.object(config, "SELECTED_PATH", log_path),
            ):
                posts = discover._selected_instagram_posts()
                candidates = discover._mention_candidates(posts)

            self.assertEqual(candidates["alpha"].mentions, 2)

    def test_similar_accounts_are_merged_with_evidence(self) -> None:
        similar = SimpleNamespace(username="Nearby", full_name="Near By", biography="photos")
        profile = SimpleNamespace(get_similar_accounts=lambda: iter([similar]))
        fake_instaloader = SimpleNamespace(
            Profile=SimpleNamespace(from_username=lambda _context, _seed: profile)
        )
        candidates = {}
        with (
            patch.object(discover.auth, "active_username", return_value="viewer"),
            patch.object(discover.auth, "get_loader", return_value=SimpleNamespace(context=object())),
            patch.dict("sys.modules", {"instaloader": fake_instaloader}),
        ):
            discover._add_similar_candidates(candidates, {"seed"})

        self.assertEqual(candidates["nearby"].similar_to, {"seed"})
        self.assertEqual(candidates["nearby"].biography, "photos")

    def test_llm_can_only_choose_supplied_handles(self) -> None:
        ranked = [discover.Candidate("valid", mentions=2), discover.Candidate("other", mentions=1)]
        with (
            patch.object(discover.llm, "resolve_api_key", return_value="key"),
            patch.object(discover.llm, "call", return_value="@invented\n@valid"),
        ):
            chosen = discover._llm_select(ranked, [("seed", "street photos")], 2)

        self.assertEqual([candidate.username for candidate in chosen], ["valid"])

    def test_run_is_preview_only_unless_add_is_requested(self) -> None:
        candidate = discover.Candidate("new_account", mentions=1)
        common = (
            patch.object(discover, "_selected_instagram_posts", return_value=[("seed", "@new_account")]),
            patch.object(discover, "_mention_candidates", return_value={"new_account": candidate}),
            patch.object(discover, "_add_similar_candidates"),
            patch.object(discover, "_llm_select", return_value=[candidate]),
            patch.object(discover.accounts, "list_accounts", return_value={"instagram": []}),
            patch.object(discover.accounts, "add", return_value=True),
        )
        with common[0], common[1], common[2], common[3], common[4], common[5] as add_account:
            discover.run(add=False)
            add_account.assert_not_called()

        with (
            patch.object(discover, "_selected_instagram_posts", return_value=[("seed", "@new_account")]),
            patch.object(discover, "_mention_candidates", return_value={"new_account": candidate}),
            patch.object(discover, "_add_similar_candidates"),
            patch.object(discover, "_llm_select", return_value=[candidate]),
            patch.object(discover.accounts, "list_accounts", return_value={"instagram": []}),
            patch.object(discover.accounts, "add", return_value=True) as add_account,
        ):
            discover.run(add=True)
            add_account.assert_called_once_with("instagram", "new_account")


if __name__ == "__main__":
    unittest.main()
