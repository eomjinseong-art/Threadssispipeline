import unittest
from refill_queue import ordered_pending, check


class RefillQueueTest(unittest.TestCase):
    def test_order_matches_make_shorts(self):
        recs = [{"EP": 1, "제목": "a", "YouTube": "완료"}, {"EP": 2, "제목": "b", "YouTube": "대기"},
                {"EP": 3, "제목": "c", "YouTube": "대기"}]
        self.assertEqual([i for i, _ in ordered_pending(recs)], [3, 4])

    def test_banned_words(self):
        spec = {"segments": [{"type": "hook", "text": "대전 " * 130}, {"type": "chat", "text": "x"}, {"type": "key", "text": "x"},
                             {"type": "question", "text": "x"}], "title": "t #Shorts", "description": "창작"}
        self.assertTrue(any("대전" in e for e in check(spec)))


if __name__ == "__main__":
    unittest.main()
