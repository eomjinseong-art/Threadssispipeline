import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_script import (
    COMPLETE_STATUS,
    PENDING_STATUS,
    effective_youtube_status,
    pick_youtube_pending_row,
    seed_youtube_updates,
)


def _row(ep, status="완료", youtube="", title="제목"):
    return {
        "Status": status,
        "EP": ep,
        "제목": title,
        "사연": "사연",
        "현실언니": "현실",
        "공감언니": "공감",
        "폭주언니": "폭주",
        "질문": "질문?",
        "YouTube": youtube,
    }


class YouTubeQueueTests(unittest.TestCase):
    def test_empty_youtube_seeds_42_complete_43_pending(self):
        records = [_row("042"), _row("43"), _row("102", status="대기")]
        seeded = seed_youtube_updates(records)
        by_row = dict(seeded)
        self.assertEqual(by_row[2], COMPLETE_STATUS)  # EP 42
        self.assertEqual(by_row[3], PENDING_STATUS)  # EP 43
        self.assertEqual(by_row[4], PENDING_STATUS)  # EP 102
        self.assertEqual(effective_youtube_status(_row("42")), COMPLETE_STATUS)
        self.assertEqual(effective_youtube_status(_row("43")), PENDING_STATUS)

    def test_does_not_overwrite_explicit_youtube_cell(self):
        records = [_row("50", youtube="완료")]
        self.assertEqual(seed_youtube_updates(records), [])
        self.assertEqual(effective_youtube_status(records[0]), COMPLETE_STATUS)

    def test_picks_lowest_ep_not_first_threads_pending(self):
        records = [
            _row("40", status="완료", youtube=""),  # seeded YouTube 완료
            _row("43", status="완료", youtube="", title="내 결혼을 반대하는 절친"),
            _row("101", status="완료", youtube="대기"),
            _row("102", status="대기", youtube="대기", title="친정엄마의 과도한 간섭"),
        ]
        idx, row = pick_youtube_pending_row(records)
        self.assertEqual(idx, 3)
        self.assertEqual(str(row["EP"]), "43")
        self.assertEqual(row["제목"], "내 결혼을 반대하는 절친")
        self.assertEqual(row["Status"], "완료")

    def test_skips_threads_pending_if_youtube_already_done(self):
        records = [
            _row("102", status="대기", youtube="완료"),
            _row("43", status="완료", youtube="대기"),
        ]
        idx, row = pick_youtube_pending_row(records)
        self.assertEqual(str(row["EP"]), "43")
        self.assertEqual(idx, 3)

    def test_empty_when_all_youtube_complete(self):
        records = [_row("43", youtube="완료"), _row("102", status="대기", youtube="완료")]
        idx, row = pick_youtube_pending_row(records)
        self.assertIsNone(idx)
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
