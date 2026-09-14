import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_shorts import run


class MakeShortsOrchestratorTests(unittest.TestCase):
    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_short", return_value="vid123")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row43.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row43.json")
    @patch("make_shorts.fetch_pending_script")
    @patch("make_shorts.load_worksheet")
    def test_marks_youtube_complete_only_after_upload(
        self,
        load_ws,
        fetch,
        _gen,
        _asm,
        upload,
        mark,
    ):
        ws = MagicMock()
        load_ws.return_value = ws
        fetch.return_value = (43, {"title": "EP.43 테스트", "row_index": 43}, "output/script_row43.json")
        self.assertEqual(run(), 0)
        upload.assert_called_once_with("output/final_row43.mp4", "output/script_row43.json")
        mark.assert_called_once_with(ws, 43)

    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_short", side_effect=RuntimeError("upload failed"))
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row43.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row43.json")
    @patch("make_shorts.fetch_pending_script")
    @patch("make_shorts.load_worksheet")
    def test_upload_failure_does_not_mark(
        self,
        load_ws,
        fetch,
        _gen,
        _asm,
        _upload,
        mark,
    ):
        load_ws.return_value = MagicMock()
        fetch.return_value = (43, {"title": "EP.43 테스트"}, "output/script_row43.json")
        with self.assertRaises(RuntimeError):
            run()
        mark.assert_not_called()

    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_short", return_value="vid123")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row43.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row43.json")
    @patch("make_shorts.fetch_pending_script")
    @patch("make_shorts.load_worksheet")
    @patch("upload_video.post_to_threads")
    def test_does_not_post_to_threads(
        self,
        threads,
        load_ws,
        fetch,
        _gen,
        _asm,
        _upload,
        mark,
    ):
        load_ws.return_value = MagicMock()
        fetch.return_value = (43, {"title": "EP.43"}, "output/script_row43.json")
        self.assertEqual(run(), 0)
        threads.assert_not_called()
        mark.assert_called_once()

    @patch("make_shorts.mark_youtube_complete")
    @patch("make_shorts.upload_short")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row102.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row102.json")
    def test_dry_run_skips_upload_and_sheet(self, _gen, _asm, upload, mark):
        fixture = str(Path(__file__).resolve().parent / "fixtures" / "script_ep102.json")
        self.assertEqual(run(dry_run=True, script_path=fixture), 0)
        upload.assert_not_called()
        mark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
