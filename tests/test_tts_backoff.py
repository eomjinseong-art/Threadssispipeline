"""edge-tts 429 backoff. The 2026-10-21 render died on the first 429 with no delay."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1] / "sayeon_engine"
if str(ENGINE) not in sys.path:
    sys.path.append(str(ENGINE))

import common


_RATE = "aiohttp.client_exceptions.WSServerHandshakeError: 429, message='Invalid response status'"


class TtsBackoffTests(unittest.TestCase):
    def setUp(self):
        common._edge_rate_limited = False

    def test_handshake_429_is_a_rate_limit_but_story_text_is_not(self):
        self.assertTrue(common.tts_error_is_rate_limit(RuntimeError("cmd --text 안녕\n" + _RATE)))
        self.assertTrue(common.tts_error_is_rate_limit(RuntimeError("Too Many Requests")))
        self.assertFalse(
            common.tts_error_is_rate_limit(RuntimeError("edge-tts --text 429번이라고 했어요\nconnection reset"))
        )

    def test_429_sleeps_then_succeeds(self):
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.wav")
            state = {"edge": 0}

            def fake_run(cmd):
                if "--write-media" in cmd:
                    state["edge"] += 1
                    if state["edge"] < 3:
                        raise RuntimeError(_RATE)
                    return ""
                if cmd and cmd[0] == "ffprobe":
                    return "1.50\n"
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".wav"):
                        Path(arg).parent.mkdir(parents=True, exist_ok=True)
                        Path(arg).write_bytes(b"")
                return ""

            with patch.object(common, "run", side_effect=fake_run), patch.object(common.time, "sleep", side_effect=sleeps.append):
                dur = common.tts("첫 문장입니다.", "ko-KR-SunHiNeural", out, cache_dir=os.path.join(tmp, "cache"))
        self.assertEqual(dur, 1.5)
        self.assertEqual(state["edge"], 3)
        self.assertEqual(sleeps, [2, 4])
        self.assertFalse(common._edge_rate_limited)

    def test_exhausted_429_falls_back_once_then_skips_edge(self):
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            state = {"edge": 0, "openai": 0}

            def fake_run(cmd):
                if "--write-media" in cmd:
                    state["edge"] += 1
                    raise RuntimeError(_RATE)
                if cmd and cmd[0] == "ffprobe":
                    return "1.25\n"
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".wav"):
                        Path(arg).write_bytes(b"")
                return ""

            def fake_openai(text, voice, rate, pitch, mp3):
                state["openai"] += 1
                Path(mp3).write_bytes(b"mp3")

            env = {"OPENAI_API_KEY": "test-key", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "openai_tts", side_effect=fake_openai
            ), patch.object(common.time, "sleep", side_effect=sleeps.append):
                first = common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c1"))
                second = common.tts("다른 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "b.wav"), cache_dir=os.path.join(tmp, "c2"))
        self.assertEqual(first, 1.25)
        self.assertEqual(second, 1.25)
        self.assertEqual(state["edge"], len(common.TTS_RATE_LIMIT_DELAYS) + 1)
        self.assertEqual(state["openai"], 2)
        self.assertEqual(sleeps, list(common.TTS_RATE_LIMIT_DELAYS))
        self.assertTrue(common._edge_rate_limited)

    def test_exhausted_429_without_openai_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(cmd):
                if "--write-media" in cmd:
                    raise RuntimeError(_RATE)
                return ""

            env = {"OPENAI_API_KEY": "", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common.time, "sleep", return_value=None
            ):
                with self.assertRaises(RuntimeError) as caught:
                    common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertIn("429", str(caught.exception))

    def test_other_errors_retry_immediately_then_fall_back(self):
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            state = {"edge": 0}

            def fake_run(cmd):
                if "--write-media" in cmd:
                    state["edge"] += 1
                    raise RuntimeError("connection reset by peer")
                if cmd and cmd[0] == "ffprobe":
                    return "1.0\n"
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".wav"):
                        Path(arg).write_bytes(b"")
                return ""

            env = {"OPENAI_API_KEY": "test-key", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "openai_tts", return_value=None
            ), patch.object(common.time, "sleep", side_effect=sleeps.append):
                common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertEqual(state["edge"], 3)
        self.assertEqual(sleeps, [])
        self.assertFalse(common._edge_rate_limited)

    def test_render_step_passes_openai_key_and_buffers_unit_test_logs(self):
        text = Path(__file__).resolve().parents[1].joinpath(".github/workflows/daily_shorts.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests -b", text)
        render = text.split("대기 사연", 1)[1].split("렌더된 mp4", 1)[0]
        self.assertIn("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}", render)


if __name__ == "__main__":
    unittest.main()
