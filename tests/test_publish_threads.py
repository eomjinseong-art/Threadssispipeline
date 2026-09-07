import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publish_threads import THREADS_MAX_CHARS, assemble_post, build_threads_text


class BuildThreadsTextTests(unittest.TestCase):
    def test_short_story_keeps_all_sections(self):
        text = build_threads_text(
            {
                "EP": "031",
                "제목": "야근 강요",
                "사연": "오늘도 야근을 시켰어요.\n거절했더니 표정이 변했습니다.",
                "현실언니": "문자로 남기세요.",
                "공감언니": "그 표정 변화, 이미 신호예요.",
                "폭주언니": "그 회사 지금 나가도 됩니다.",
                "질문": "여러분이라면 어떻게 하겠어요?",
            }
        )
        self.assertIn("EP.031 야근 강요", text)
        self.assertIn("오늘도 야근을 시켰어요.", text)
        self.assertIn("현실언니: 문자로 남기세요.", text)
        self.assertIn("공감언니:", text)
        self.assertIn("폭주언니:", text)
        self.assertIn("여러분이라면 어떻게 하겠어요?", text)
        self.assertLessEqual(len(text), THREADS_MAX_CHARS)

    def test_long_story_is_truncated_to_limit(self):
        story = "이건 아주 긴 사연입니다. " * 80
        text = build_threads_text(
            {
                "EP": "7",
                "제목": "긴글",
                "사연": story,
                "현실언니": "짧게 자르세요.",
                "공감언니": "이해해요.",
                "폭주언니": "이제 그만.",
                "질문": "어떻게 하실래요?",
            }
        )
        self.assertLessEqual(len(text), THREADS_MAX_CHARS)
        self.assertIn("현실언니:", text)
        self.assertIn("어떻게 하실래요?", text)
        self.assertTrue(text.endswith("어떻게 하실래요?") or "어떻게 하실래요?" in text)

    def test_assemble_skips_empty_story(self):
        packed = assemble_post("EP.1 제목", "", "현실언니: 조언", "질문?")
        self.assertEqual(packed, "EP.1 제목\n\n현실언니: 조언\n\n질문?")


if __name__ == "__main__":
    unittest.main()
