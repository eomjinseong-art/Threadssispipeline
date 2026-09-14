import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_shorts import run


class MakeShortsOrchestratorTests(unittest.TestCase):
    @patch("make_shorts.post_to_threads")
    @patch("make_shorts.mark_row_complete")
    @patch("make_shorts.upload_short", return_value="vid123")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row12.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row12.json")
    @patch("make_shorts.fetch_pending_script")
    @patch("make_shorts.load_worksheet")
    def test_marks_complete_only_after_upload(
        self,
        load_ws,
        fetch,
        _gen,
        _asm,
        upload,
        mark,
        _threads,
    ):
        ws = MagicMock()
        load_ws.return_value = ws
        fetch.return_value = (12, {"title": "EP.12 테스트", "row_index": 12}, "output/script_row12.json")
        self.assertEqual(run(), 0)
        upload.assert_called_once_with("output/final_row12.mp4", "output/script_row12.json")
        mark.assert_called_once_with(ws, 12)

    @patch("make_shorts.mark_row_complete")
    @patch("make_shorts.upload_short", side_effect=RuntimeError("upload failed"))
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row12.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row12.json")
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
        fetch.return_value = (12, {"title": "EP.12 테스트"}, "output/script_row12.json")
        with self.assertRaises(RuntimeError):
            run()
        mark.assert_not_called()

    @patch("make_shorts.post_to_threads", side_effect=RuntimeError("threads down"))
    @patch("make_shorts.mark_row_complete")
    @patch("make_shorts.upload_short", return_value="vid123")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row12.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row12.json")
    @patch("make_shorts.fetch_pending_script")
    @patch("make_shorts.load_worksheet")
    def test_threads_failure_keeps_success_and_complete(
        self,
        load_ws,
        fetch,
        _gen,
        _asm,
        _upload,
        mark,
        _threads,
    ):
        ws = MagicMock()
        load_ws.return_value = ws
        fetch.return_value = (9, {"title": "EP.9"}, "output/script_row9.json")
        self.assertEqual(run(), 0)
        mark.assert_called_once_with(ws, 9)

    @patch("make_shorts.mark_row_complete")
    @patch("make_shorts.upload_short")
    @patch("make_shorts.assemble_from_manifest", return_value="output/final_row40.mp4")
    @patch("make_shorts.generate_media", return_value="output/manifest_row40.json")
    def test_dry_run_skips_upload_and_sheet(self, _gen, _asm, upload, mark):
        fixture = str(Path(__file__).resolve().parent / "fixtures" / "script_ep40.json")
        self.assertEqual(run(dry_run=True, script_path=fixture), 0)
        upload.assert_not_called()
        mark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
