import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shorts_style import VIDEO_WIDTH, get_font, wrap_korean


class WrapKoreanTests(unittest.TestCase):
    def test_prefers_spaces_and_keeps_gansub_together(self):
        font = get_font(72)
        title = "EP.102 친정엄마의 과도한 간섭"
        lines = wrap_korean(title, font, VIDEO_WIDTH - 160)
        self.assertTrue(any("간섭" in ln for ln in lines), lines)
        self.assertFalse(any(ln.strip() == "섭" for ln in lines), lines)
        self.assertFalse(any(ln.endswith("간") and "간섭" not in ln for ln in lines), lines)
        for ln in lines:
            self.assertNotEqual(len(ln.strip()), 1, lines)

    def test_wraps_on_spaces_when_narrow(self):
        font = get_font(72)
        # 폭을 아주 좁혀 강제 개행
        lines = wrap_korean("안녕 하세요", font, 80)
        joined = "".join(lines).replace(" ", "")
        self.assertIn("안녕", joined)
        self.assertIn("하세요", joined)
        self.assertFalse(any(ln.strip() == "요" for ln in lines), lines)

    def test_single_short_line_stays_one_line(self):
        font = get_font(72)
        lines = wrap_korean("짧은제목", font, VIDEO_WIDTH - 160)
        self.assertEqual(lines, ["짧은제목"])


if __name__ == "__main__":
    unittest.main()
