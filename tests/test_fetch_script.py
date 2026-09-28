import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_script import (
    build_narration,
    build_script,
    build_slides,
    validate_row,
    write_script,
)
from shorts_style import script_path_for_row

SAMPLE_ROW = {
    "Status": "대기",
    "EP": "40",
    "제목": "외모를 평가하는 남편",
    "사연": "결혼 3년 차예요.\n남편이 회식에서 살쪘다고 했어요.",
    "현실언니": "그건 장난이 아니에요.",
    "공감언니": "그 웃음이 제일 아팠을 거예요.",
    "폭주언니": "그 자리에서 일어나세요.",
    "질문": "여러분이라면 바로 말렸을까요?",
}


class FetchScriptHelperTests(unittest.TestCase):
    def test_build_slides_is_story_then_question(self):
        slides = build_slides(SAMPLE_ROW)
        self.assertEqual([s["type"] for s in slides], ["story", "question"])
        self.assertEqual([s["index"] for s in slides], [0, 1])
        self.assertNotIn("현실언니", slides[0]["narration_text"])
        self.assertNotIn("안녕하세요, 오늘도 사연", slides[0]["narration_text"])
        self.assertIn("남편이 회식에서 살쪘다고 했어요.", slides[0]["narration_text"])
        self.assertEqual(slides[1]["narration_text"], SAMPLE_ROW["질문"])

    def test_build_script_title_leads_with_conflict_not_ep(self):
        script = build_script(SAMPLE_ROW, row_index=12, today="2026-09-14")
        self.assertEqual(script["row_index"], 12)
        self.assertEqual(script["title"], "외모를 평가하는 남편, 결말은?")
        self.assertFalse(script["title"].startswith("EP"))
        self.assertEqual(script["date"], "2026-09-14")
        self.assertEqual(script["format"], "twist")
        self.assertIn(SAMPLE_ROW["질문"], build_narration(script["slides"]))
        self.assertNotIn("현실언니", script["narration"])
        self.assertNotIn("폭주언니", script["narration"])

    def test_missing_sister_columns_are_not_rejected(self):
        row = {
            "EP": "40",
            "제목": "외모를 평가하는 남편",
            "사연": "남편이 회식에서 살쪘다고 했어요. 나는 웃고 넘어갔습니다.",
        }
        script = build_script(row, row_index=4, today="2026-09-14")
        self.assertIn("여러분이라면 참으실 수 있나요?", script["narration"])
        self.assertNotIn("현실언니", script["narration"])

    def test_known_ep_is_adapted_with_twist(self):
        row = dict(
            SAMPLE_ROW,
            EP="70",
            제목="반지 대신 청구서",
            사연="기념일에 반지를 받았어요.\n일주일 뒤에 반반 하자더라고요.",
            질문="원래 질문?",
        )
        script = build_script(row, row_index=9, today="2026-09-28")
        self.assertIn("반반", script["title"])
        self.assertFalse(script["title"].startswith("EP"))
        self.assertIn("돌려", script["narration"])
        self.assertNotIn("현실언니", script["narration"])
        self.assertIn("여러분이라면 반반 하셨을까요?", script["slides"][-1]["narration_text"])

    def test_validate_row_rejects_empty_story(self):
        bad = dict(SAMPLE_ROW, 사연="")
        with self.assertRaises(SystemExit):
            validate_row(bad, "40")

    def test_write_script_is_row_based(self):
        script = build_script(SAMPLE_ROW, row_index=77, today="2026-09-14")
        path = write_script(script, 77)
        self.assertEqual(path, script_path_for_row(77))
        self.assertTrue(Path(path).is_file())
        self.assertIn("script_row77.json", path)
        self.assertNotIn("script_2026", path)


if __name__ == "__main__":
    unittest.main()
