import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_script import (
    INTRO,
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
    def test_build_slides_has_three_types(self):
        slides = build_slides(SAMPLE_ROW)
        self.assertEqual([s["type"] for s in slides], ["story", "reactions", "question"])
        self.assertEqual([s["index"] for s in slides], [0, 1, 2])
        self.assertIn(INTRO, slides[0]["narration_text"])
        self.assertIn("현실언니", slides[1]["display_text"])
        self.assertEqual(slides[2]["narration_text"], SAMPLE_ROW["질문"])

    def test_build_script_uses_row_index(self):
        script = build_script(SAMPLE_ROW, row_index=12, today="2026-09-14")
        self.assertEqual(script["row_index"], 12)
        self.assertEqual(script["title"], "EP.40 외모를 평가하는 남편")
        self.assertEqual(script["date"], "2026-09-14")
        self.assertIn(SAMPLE_ROW["질문"], build_narration(script["slides"]))

    def test_validate_row_rejects_empty_column(self):
        bad = dict(SAMPLE_ROW, 질문="")
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
