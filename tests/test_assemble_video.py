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
    build_intro_card,
    build_segment,
    concat_segments,
    escape_ass_path_for_filter,
    get_duration,
    mix_bgm,
    run,
)
from generate_media import build_background, build_typing_ass
from shorts_style import INTRO_BG, VIDEO_HEIGHT, VIDEO_WIDTH, find_bgm_path


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

    def test_intro_card_is_mostly_black_with_white_title(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intro.png"
            build_intro_card("EP.40 외모를 평가하는 남편", str(path))
            img = Image.open(path).convert("RGB")
            self.assertEqual(img.size, (VIDEO_WIDTH, VIDEO_HEIGHT))
            self.assertEqual(img.getpixel((20, 20)), INTRO_BG)
            pixels = list(img.getdata())
            blackish = sum(1 for r, g, b in pixels if r < 20 and g < 20 and b < 20)
            self.assertGreater(blackish / len(pixels), 0.85)
            bright = sum(1 for r, g, b in pixels if r > 200 and g > 200 and b > 200)
            self.assertGreater(bright, 200)

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
            box = img.crop((w // 4, h // 2 - 120, w * 3 // 4, h // 2 + 120))
            dark = sum(1 for r, g, b in box.getdata() if (r + g + b) / 3 < 90)
            self.assertGreater(dark, 80, "자막이 타지 않은 것 같습니다")

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


if __name__ == "__main__":
    unittest.main()
