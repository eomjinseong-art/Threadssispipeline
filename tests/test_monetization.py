import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import upload_video  # noqa: E402
from monetization import COUPANG_NOTICE, PARTNER_LINK, comment_text, with_disclosure  # noqa: E402


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def next_chunk(self):
        if isinstance(self.result, Exception):
            raise self.result
        return None, {"id": "VID"}


class MonetizationTest(unittest.TestCase):
    def test_first_line_notice_second_line_link(self):
        lines = with_disclosure("사연 요약\n\n#Shorts").splitlines()
        self.assertEqual(lines[0], "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.")
        self.assertIn(PARTNER_LINK, lines[1])
        self.assertEqual(lines[-1], "#Shorts")

    def test_idempotent_and_comment(self):
        once = with_disclosure("x")
        self.assertEqual(with_disclosure(once), once)
        self.assertTrue(comment_text("질문").startswith(COUPANG_NOTICE))
        self.assertEqual(comment_text(comment_text("질문")), comment_text("질문"))
        self.assertTrue(PARTNER_LINK.startswith("https://tinalinkeom.vercel.app/?utm_source=youtube&utm_medium=shorts&utm_campaign=waitmybabe"))

    def test_upload_sets_paid_flag_and_falls_back(self):
        from googleapiclient.errors import HttpError

        calls = []
        err = HttpError(mock.Mock(status=400, reason="bad"), b"{}")

        def insert(part, body, media_body):
            calls.append((part, dict(body)))
            return FakeRequest(err if "paidProductPlacementDetails" in part else None)

        yt = mock.Mock()
        yt.videos.return_value.insert.side_effect = insert
        with mock.patch.object(upload_video, "build", return_value=yt), \
                mock.patch.object(upload_video, "MediaFileUpload"):
            vid = upload_video.upload_video(None, "v.mp4", {"title": "t", "description": "d", "tags": []})
        self.assertEqual(vid, "VID")
        self.assertEqual(calls[0][0], "snippet,status,paidProductPlacementDetails")
        self.assertTrue(calls[0][1]["paidProductPlacementDetails"]["hasPaidProductPlacement"])
        self.assertTrue(calls[0][1]["snippet"]["description"].startswith(COUPANG_NOTICE))
        self.assertEqual(calls[1][0], "snippet,status")


if __name__ == "__main__":
    unittest.main()
