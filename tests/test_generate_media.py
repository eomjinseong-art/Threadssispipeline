import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_media import (
    EDGE_TTS_BOUNDARY,
    SPEAKER_ASS_COLORS,
    build_background,
    build_typing_ass,
    color_for_position,
    find_speaker_segments,
    make_communicate,
    seconds_to_ass_time,
)
from shorts_style import BG_COLOR


class GenerateMediaHelperTests(unittest.TestCase):
    def test_edge_tts_boundary_is_word(self):
        self.assertEqual(EDGE_TTS_BOUNDARY, "WordBoundary")
        comm = make_communicate("안녕하세요")
        self.assertEqual(comm.tts_config.boundary, "WordBoundary")
        self.assertNotEqual(comm.tts_config.boundary, "SentenceBoundary")

    def test_seconds_to_ass_time(self):
        self.assertEqual(seconds_to_ass_time(0), "0:00:00.00")
        self.assertEqual(seconds_to_ass_time(2.2), "0:00:02.20")
        self.assertEqual(seconds_to_ass_time(65.5), "0:01:05.50")

    def test_speaker_colors_follow_narration_position(self):
        narration = (
            "현실언니는 이렇게 말합니다. A "
            "공감언니는 이렇게 말합니다. B "
            "그리고 폭주언니는 이렇게 말합니다. C"
        )
        segs = find_speaker_segments(narration)
        self.assertEqual([name for _i, name in segs], ["현실언니", "공감언니", "폭주언니"])
        real_pos = narration.find("A")
        emp_pos = narration.find("B")
        rage_pos = narration.find("C")
        self.assertEqual(color_for_position(real_pos, segs), SPEAKER_ASS_COLORS["현실언니"])
        self.assertEqual(color_for_position(emp_pos, segs), SPEAKER_ASS_COLORS["공감언니"])
        self.assertEqual(color_for_position(rage_pos, segs), SPEAKER_ASS_COLORS["폭주언니"])

    def test_build_typing_ass_writes_nonempty_dialogue(self):
        narration = "안녕하세요 오늘도 사연"
        boundaries = [
            {"text": "안녕하세요", "offset": 0.0, "duration": 0.3},
            {"text": "오늘도", "offset": 0.3, "duration": 0.25},
            {"text": "사연", "offset": 0.55, "duration": 0.2},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "00.ass"
            build_typing_ass(boundaries, 1.0, narration, "story", str(ass_path))
            text = ass_path.read_text(encoding="utf-8")
            dialogues = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
            self.assertGreaterEqual(len(dialogues), 3)
            for line in dialogues:
                spoken = line.split(",", 9)[-1].strip()
                self.assertTrue(spoken, "ASS Dialogue 텍스트가 비면 자막이 안 나옵니다")
            self.assertIn("안녕하세요", text)

    def test_background_is_paper_color(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bg.png"
            build_background("story", str(out))
            img = Image.open(out)
            self.assertEqual(img.size, (1080, 1920))
            self.assertEqual(img.getpixel((10, 10)), BG_COLOR)


if __name__ == "__main__":
    unittest.main()
