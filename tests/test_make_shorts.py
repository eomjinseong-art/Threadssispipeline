import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_shorts import run
from sayeon_render import DurationOutOfRange

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

    @patch("make_shorts.mark_youtube_hold")
    @patch("make_shorts.notify_failure")
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short", return_value="vid999")
    @patch(
        "make_shorts.render_spec",
        side_effect=[DurationOutOfRange(42.9), ("output/y.mp4", 50.0)],
    )
    @patch(
        "make_shorts.find_spec_for_title",
        side_effect=[
            ("sayeon_specs/sayeon_ep079.json", SPEC),
            ("sayeon_specs/sayeon_ep080.json", {**SPEC, "title": "다음 사연 #Shorts"}),
        ],
    )
    @patch(
        "make_shorts.find_pending_row",
        side_effect=[
            (162, {"제목": "시어머니 전용 카드키를 달라는 남편, 결말은?"}),
            (163, {"제목": "다음 사연"}),
        ],
    )
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_short_spec_is_held_and_next_row_uploads(
        self, _posted, load_ws, _pick, _find, _render, upload, mark, notify, hold
    ):
        ws = MagicMock()
        load_ws.return_value = ws
        self.assertEqual(run(), 0)
        hold.assert_called_once_with(ws, 162)
        notify.assert_called_once()
        upload.assert_called_once()
        self.assertEqual(upload.call_args[0][1]["title"], "다음 사연 #Shorts")
        mark.assert_called_once_with(ws, 163)

    @patch("make_shorts.mark_youtube_hold")
    @patch("make_shorts.notify_failure")
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short")
    @patch("make_shorts.render_spec", side_effect=DurationOutOfRange(42.9))
    @patch("make_shorts.find_spec_for_title", return_value=("sayeon_specs/x.json", SPEC))
    @patch("make_shorts.find_pending_row", return_value=(162, {"제목": "짧은 사연"}))
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_hold_does_not_retry_the_same_row_forever(
        self, _posted, load_ws, _pick, _find, _render, upload, mark, _notify, hold
    ):
        load_ws.return_value = MagicMock()
        self.assertEqual(run(), 1)
        self.assertEqual(hold.call_count, 1)
        upload.assert_not_called()
        mark.assert_not_called()

    @patch("make_shorts.mark_youtube_hold")
    @patch("make_shorts.notify_failure")
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_spec_short")
    @patch("make_shorts.render_spec", side_effect=DurationOutOfRange(40.0))
    @patch("make_shorts.find_spec_for_title", return_value=("sayeon_specs/x.json", SPEC))
    @patch(
        "make_shorts.find_pending_row",
        side_effect=[(i, {"제목": f"짧은 {i}"}) for i in range(2, 9)],
    )
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_stops_after_five_short_specs(self, _posted, load_ws, _pick, _find, _render, upload, mark, _notify, hold):
        load_ws.return_value = MagicMock()
        self.assertEqual(run(), 1)
        self.assertEqual(hold.call_count, 5)
        upload.assert_not_called()
        mark.assert_not_called()

    @patch("make_shorts.mark_youtube_hold")
    @patch("make_shorts.notify_failure")
    @patch("make_shorts.render_spec", side_effect=DurationOutOfRange(42.9))
    @patch("make_shorts.find_spec_for_title", return_value=("sayeon_specs/x.json", SPEC))
    @patch("make_shorts.find_pending_row", return_value=(162, {"제목": "짧은 사연"}))
    @patch("make_shorts.load_worksheet")
    @patch("make_shorts.already_posted_short_today", return_value=False)
    def test_dry_run_does_not_hold_a_short_spec(self, _posted, load_ws, _pick, _find, _render, _notify, hold):
        load_ws.return_value = MagicMock()
        with self.assertRaises(DurationOutOfRange):
            run(dry_run=True)
        hold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
