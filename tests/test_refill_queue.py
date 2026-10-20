import json
import unittest
from pathlib import Path

from refill_queue import check, ordered_pending


class RefillQueueTest(unittest.TestCase):
    def test_order_matches_make_shorts(self):
        recs = [{"EP": 1, "제목": "a", "YouTube": "완료"}, {"EP": 2, "제목": "b", "YouTube": "대기"},
                {"EP": 3, "제목": "c", "YouTube": "대기"}]
        self.assertEqual([i for i, _ in ordered_pending(recs)], [3, 4])

    def test_banned_words(self):
        spec = {"segments": [{"type": "hook", "text": "대전 " * 130}, {"type": "chat", "text": "x"}, {"type": "key", "text": "x"},
                             {"type": "question", "text": "x"}], "title": "t #Shorts", "description": "창작"}
        self.assertTrue(any("대전" in e for e in check(spec)))

    def test_ep79_passes_length_check(self):
        spec = json.loads((Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep079.json").read_text(encoding="utf-8"))
        self.assertEqual(check(spec), [])

    def test_short_beats_fail_length_estimate(self):
        spec = json.loads((Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep079.json").read_text(encoding="utf-8"))
        for seg in spec["segments"]:
            seg["spoken"] = "짧아요."
            seg.pop("tail", None)
        errs = check(spec)
        self.assertTrue(any("예상 길이" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
