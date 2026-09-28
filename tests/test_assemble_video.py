import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assemble_video import (
    BGM_FLOOR_WEIGHT,
    BGM_PRE_DUCK_VOLUME,
    build_intro_card,
    build_segment,
    concat_segments,
    escape_ass_path_for_filter,
    get_duration,
    mix_bgm,
    run,
)
from generate_media import build_background, build_typing_ass
from shorts_style import (
    INTRO_BG,
    INTRO_DURATION,
    INTRO_FG,
    SAFE_BOTTOM,
    SAFE_LEFT,
    SAFE_RIGHT,
    SAFE_TOP,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    find_bgm_path,
)


def _ffprobe_json(path: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(result.stdout)


def _extract_frame(video: str, t: float, out_png: str) -> None:
    run([
        "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video,
        "-frames:v", "1", out_png,
    ])


class AssembleHelperTests(unittest.TestCase):
    def test_run_uses_utf8_encoding(self):
        source = inspect.getsource(run)
        self.assertIn('encoding="utf-8"', source)
        self.assertIn('errors="replace"', source)

    def test_escape_ass_path_escapes_windows_drive(self):
        escaped = escape_ass_path_for_filter(r"C:\temp\00.ass")
        self.assertIn("\\:", escaped)

    def test_intro_card_is_beige_hook_inside_safe_area(self):
        from PIL import Image

        self.assertGreaterEqual(INTRO_DURATION, 1.0)
        self.assertLessEqual(INTRO_DURATION, 2.0)
        self.assertNotEqual(INTRO_BG, (0, 0, 0))
        self.assertGreater(INTRO_BG[0], 200)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intro.png"
            build_intro_card("도어락 비번 알아낸 시어머니, 결말은?", str(path))
            img = Image.open(path).convert("RGB")
            self.assertEqual(img.size, (VIDEO_WIDTH, VIDEO_HEIGHT))
            self.assertEqual(img.getpixel((20, 20)), INTRO_BG)
            ink = []
            for y in range(img.height):
                for x in range(img.width):
                    pixel = img.getpixel((x, y))
                    if sum(pixel) + 90 < sum(INTRO_BG):
                        ink.append((x, y))
            self.assertGreater(len(ink), 200)
            for x, y in ink:
                self.assertGreaterEqual(x, SAFE_LEFT - 2, (x, y))
                self.assertLess(x, SAFE_RIGHT + 2, (x, y))
                self.assertGreaterEqual(y, SAFE_TOP - 2, (x, y))
                self.assertLess(y, SAFE_BOTTOM, (x, y))
            self.assertNotEqual(INTRO_FG, (255, 255, 255))

    def test_mix_bgm_skips_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=25",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                str(video),
            ])
            out = mix_bgm(str(video), bgm_path="/tmp/this-bgm-does-not-exist.mp3")
            self.assertEqual(out, str(video))

    def test_segment_burns_subtitles_and_has_shorts_codec(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            image = tmp_path / "bg.png"
            audio = tmp_path / "a.aac"
            ass = tmp_path / "t.ass"
            seg = tmp_path / "seg.mp4"
            build_background("story", str(image))
            run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2.0", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                str(audio),
            ])
            build_typing_ass(
                [
                    {"text": "자막검증텍스트", "offset": 0.0, "duration": 1.8},
                ],
                2.0,
                "자막검증텍스트",
                "story",
                str(ass),
            )
            build_segment(str(image), str(audio), str(ass), str(seg))
            probe = _ffprobe_json(str(seg))
            video_stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
            audio_stream = next(s for s in probe["streams"] if s["codec_type"] == "audio")
            self.assertEqual(video_stream["codec_name"], "h264")
            self.assertEqual(int(video_stream["width"]), 1080)
            self.assertEqual(int(video_stream["height"]), 1920)
            self.assertEqual(video_stream["r_frame_rate"], "25/1")
            self.assertEqual(audio_stream["codec_name"], "aac")

            frame = tmp_path / "mid.png"
            _extract_frame(str(seg), 0.8, str(frame))
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            # Alignment 8 + MarginV 520: 자막은 화면 위쪽 고정 (가운데 재정렬 안 함)
            box = img.crop((w // 8, 480, min(w * 7 // 8, 900), 820))
            dark = sum(1 for r, g, b in box.getdata() if (r + g + b) / 3 < 90)
            self.assertGreater(dark, 80, "자막이 타지 않은 것 같습니다")
            right = img.crop((w - 150, 0, w, h))
            right_dark = sum(1 for r, g, b in right.getdata() if (r + g + b) / 3 < 90)
            self.assertLess(right_dark, 40, "오른쪽 버튼 영역에 자막이 있습니다")
            top = img.crop((0, 0, w, 200))
            top_dark = sum(1 for r, g, b in top.getdata() if (r + g + b) / 3 < 90)
            self.assertLess(top_dark, 40, "위 검색창 영역에 자막이 있습니다")
            bottom = img.crop((0, h - 420, w, h))
            bottom_dark = sum(1 for r, g, b in bottom.getdata() if (r + g + b) / 3 < 90)
            self.assertLess(bottom_dark, 40, "하단 제목 영역에 자막이 있습니다")

    def test_concat_keeps_intro_then_content(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            intro = tmp_path / "intro.mp4"
            content = tmp_path / "content.mp4"
            final = tmp_path / "final.mp4"
            run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=25",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2.2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                str(intro),
            ])
            run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=0xF6F6F4:s=1080x1920:r=25",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "1.0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                str(content),
            ])
            concat_segments([str(intro), str(content)], str(final))
            self.assertLess(get_duration(str(final)), 4.0)
            frame0 = tmp_path / "t0.png"
            _extract_frame(str(final), 0.05, str(frame0))
            img = Image.open(frame0).convert("RGB")
            avg = sum(sum(p) for p in img.getdata()) / (len(list(img.getdata())) * 3)
            self.assertLess(avg, 25)

    def test_repo_has_original_bgm(self):
        path = find_bgm_path()
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        self.assertGreater(os.path.getsize(path), 1000)
        dur = get_duration(path)
        self.assertGreaterEqual(dur, 10.0)
        self.assertLessEqual(dur, 15.0)

    def test_bgm_mix_is_audible_under_speech(self):
        self.assertGreaterEqual(BGM_PRE_DUCK_VOLUME, 0.18)
        self.assertLessEqual(BGM_PRE_DUCK_VOLUME, 0.20)
        self.assertGreaterEqual(BGM_FLOOR_WEIGHT, 0.12)
        self.assertLessEqual(BGM_FLOOR_WEIGHT, 0.15)
        source = inspect.getsource(mix_bgm)
        self.assertIn("BGM_PRE_DUCK_VOLUME", source)
        self.assertIn("BGM_FLOOR_WEIGHT", source)


if __name__ == "__main__":
    unittest.main()
