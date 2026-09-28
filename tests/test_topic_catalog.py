import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_more_stories import (
    SYSTEM_PROMPT,
    drop_duplicate_stories,
    should_generate,
    stories_to_rows,
)
from story_format import ensure_curiosity, normalize_title, youtube_title
from topic_catalog import load_adaptations, load_w_topics, topics_to_append
from upload_video import channel_posted_on_kst_day, published_on_kst_day


class TopicCatalogTests(unittest.TestCase):
    def test_w_topics_are_twist_stories_with_questions(self):
        topics = load_w_topics()
        self.assertEqual(len(topics), 21)
        titles = [topic["title"] for topic in topics]
        self.assertEqual(len(titles), len(set(titles)))
        for topic in topics:
            self.assertTrue(topic["story_lines"])
            self.assertTrue(topic["hook"])
            self.assertIn("?", topic["question"])
            self.assertTrue(topic["real"] and topic["empathy"] and topic["rage"])
            self.assertFalse(topic["title"].startswith("EP"))
            blob = " ".join(topic["story_lines"])
            self.assertNotIn("현실언니", blob)

    def test_adaptations_cover_ten_sheet_eps(self):
        items = load_adaptations()
        self.assertEqual(len(items), 10)
        self.assertIn(70, {item["ep"] for item in items})
        for item in items:
            self.assertTrue(item["twist"])
            self.assertIn("?", item["question"])
            self.assertFalse(item["title"].startswith("EP"))

    def test_append_skips_duplicate_titles_and_existing_eps(self):
        w_title = load_w_topics()[0]["title"]
        selected = topics_to_append({normalize_title(w_title)}, {70, 73}, next_ep=151)
        titles = [row["title"] for row in selected]
        self.assertNotIn(w_title, titles)
        self.assertFalse(any("반반" in title for title in titles))
        self.assertEqual(selected[0]["ep"], "151")
        originals = [row for row in selected if str(row["id"]).startswith("W")]
        self.assertEqual(len(originals), 20)
        self.assertTrue(any(row["id"] == "A74" for row in selected))

    def test_append_includes_adaptations_when_source_ep_is_absent(self):
        selected = topics_to_append(set(), set(), next_ep=1)
        self.assertEqual(len(selected), 31)
        self.assertTrue(any("반반" in row["title"] for row in selected))

    def test_refill_prompt_asks_for_twist_and_keeps_sisters(self):
        self.assertIn("사이다", SYSTEM_PROMPT)
        self.assertIn("시댁", SYSTEM_PROMPT)
        self.assertIn("여러분이라면", SYSTEM_PROMPT)
        self.assertIn("real", SYSTEM_PROMPT)
        self.assertIn("EP 번호는 넣지 마세요", SYSTEM_PROMPT)
        self.assertIn("베끼지", SYSTEM_PROMPT)

    def test_refill_triggers_when_either_queue_is_low(self):
        records = []
        for ep in range(1, 12):
            records.append(
                {
                    "Status": "대기",
                    "EP": str(ep),
                    "제목": f"제목{ep}",
                    "YouTube": "완료",
                }
            )
        trigger, _titles, _next, pending = should_generate(records)
        self.assertEqual(pending, 11)
        self.assertTrue(trigger)

        stocked = []
        for ep in range(50, 65):
            stocked.append(
                {
                    "Status": "대기",
                    "EP": str(ep),
                    "제목": f"다른{ep}",
                    "YouTube": "대기",
                }
            )
        trigger, _titles, _next, _pending = should_generate(stocked)
        self.assertFalse(trigger)

    def test_generated_rows_drop_duplicate_titles_and_ep_prefix(self):
        stories = [
            {
                "title": "EP.9 이미 있는 제목",
                "story_lines": ["한 줄."],
                "real": "r",
                "empathy": "e",
                "rage": "g",
                "question": "여러분이라면?",
            },
            {
                "title": "도어락 비번 알아낸 시어머니, 결말은?",
                "story_lines": ["훅.", "반전."],
                "real": "r",
                "empathy": "e",
                "rage": "g",
                "question": "여러분이라면 참으실 수 있나요?",
            },
        ]
        kept = drop_duplicate_stories(stories, ["이미 있는 제목"])
        self.assertEqual(len(kept), 1)
        rows = stories_to_rows(kept, 160)
        self.assertEqual(rows[0][1], "160")
        self.assertFalse(rows[0][2].startswith("EP"))
        self.assertIn("결말", rows[0][2])

    def test_youtube_title_has_no_leading_ep(self):
        title = youtube_title("EP.68 도어락 비번 알아낸 시어머니")
        self.assertTrue(title.startswith("도어락 비번 알아낸 시어머니"))
        self.assertIn("결말은?", title)
        self.assertIn("waitmybabe", title)
        self.assertTrue(title.endswith("#Shorts"))
        self.assertLessEqual(len(title), 100)
        self.assertEqual(ensure_curiosity("이미 질문?"), "이미 질문?")

    def test_kst_day_boundary(self):
        today = dt.date(2026, 9, 28)
        self.assertTrue(published_on_kst_day("2026-09-27T15:00:00Z", today))
        self.assertFalse(published_on_kst_day("2026-09-27T14:30:00Z", today))
        self.assertTrue(
            channel_posted_on_kst_day(["2026-09-27T14:30:00Z", "2026-09-28T10:00:00Z"], today)
        )
        self.assertFalse(channel_posted_on_kst_day(["2026-09-27T14:30:00Z"], today))

    def test_schedules(self):
        root = Path(__file__).resolve().parents[1]
        shorts = (root / ".github" / "workflows" / "daily_shorts.yml").read_text(encoding="utf-8")
        threads = (root / ".github" / "workflows" / "daily_threads.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 10 * * *"', shorts)
        self.assertNotIn("0 0,9,12", shorts)
        self.assertIn("append_sheet_topics.py", shorts)
        self.assertIn('cron: "30 0,9,12 * * *"', threads)


if __name__ == "__main__":
    unittest.main()
