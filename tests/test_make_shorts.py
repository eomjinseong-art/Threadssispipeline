import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_shorts import run

SPEC = {
    "channel": "sayeon",
    "episode": 73,
    "slug": "waitmybabe_EP73_test",
    "topic": "테스트 사연, 결말은?",
    "title": "테스트 사연, 결말은? #Shorts",
    "description": "설명 ※ 창작·각색",
    "tags": ["사연"],
    "segments": [
        {"type": "hook", "text": "훅"},
        {"type": "chat", "who": "시어머니", "text": "말"},
        {"type": "key", "text": "강조"},
        {"type": "question", "text": "질문?"},
    ],
}


class MakeShortsOrchestratorTests(unittest.TestCase):
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short", return_value="vid123")
    @patch("make_shorts.render_spec", return_value=("output/x.mp4", 50.0))
    @patch("make_shorts.find_spec_for_title", return_value=("sayeon_specs/x.json", SPEC))
    @patch("make_shorts.find_pending_row")
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_renders_ep67_design_and_marks_after_upload(self, _p, load_ws, pick, _find, render, upload, mark):
        ws = MagicMock()
        load_ws.return_value = ws
        pick.return_value = (155, {"제목": "테스트 사연, 결말은?"})
        self.assertEqual(run(), 0)
        render.assert_called_once_with(SPEC)
        upload.assert_called_once()
        self.assertEqual(upload.call_args[0][1]["title"], SPEC["title"])
        mark.assert_called_once_with(ws, 155)

    @patch("make_shorts.notify_failure")
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short")
    @patch("make_shorts.render_spec")
    @patch("make_shorts.find_spec_for_title", return_value=(None, None))
    @patch("make_shorts.find_pending_row", return_value=(156, {"제목": "스펙 없는 사연"}))
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_missing_spec_uploads_nothing(self, _p, _ws, _pick, _find, render, upload, mark, notify):
        self.assertEqual(run(), 0)
        render.assert_not_called()
        upload.assert_not_called()
        mark.assert_not_called()
        notify.assert_called_once()

    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short", side_effect=RuntimeError("upload failed"))
    @patch("make_shorts.render_spec", return_value=("output/x.mp4", 50.0))
    @patch("make_shorts.find_spec_for_title", return_value=("sayeon_specs/x.json", SPEC))
    @patch("make_shorts.find_pending_row", return_value=(155, {"제목": "테스트 사연, 결말은?"}))
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_upload_failure_does_not_mark(self, _p, _ws, _pick, _find, _render, _upload, mark):
        with self.assertRaises(RuntimeError):
            run()
        mark.assert_not_called()

    @patch("make_shorts.already_posted_short_today", return_value=True)
    @patch("make_shorts.find_pending_row")
    @patch("make_shorts.load_worksheet")
    def test_skips_when_channel_already_posted_today(self, load_ws, pick, _posted):
        self.assertEqual(run(), 0)
        pick.assert_not_called()
        load_ws.assert_not_called()

    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short")
    @patch("make_shorts.render_spec", return_value=("output/x.mp4", 50.0))
    def test_dry_run_skips_upload_and_sheet(self, _render, upload, mark):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        try:
            self.assertEqual(run(dry_run=True, script_path=f.name), 0)
        finally:
            os.unlink(f.name)
        upload.assert_not_called()
        mark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
