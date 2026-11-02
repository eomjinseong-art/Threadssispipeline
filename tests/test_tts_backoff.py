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

    def test_exhausted_429_uses_gtts_then_skips_edge(self):
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            state = {"edge": 0, "gtts": 0, "openai": 0}

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

            def fake_gtts(text, voice, rate, pitch, mp3):
                state["gtts"] += 1
                Path(mp3).write_bytes(b"mp3")

            def fake_openai(text, voice, rate, pitch, mp3):
                state["openai"] += 1
                Path(mp3).write_bytes(b"mp3")

            env = {"OPENAI_API_KEY": "test-key", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "gtts_tts", side_effect=fake_gtts
            ), patch.object(common, "openai_tts", side_effect=fake_openai), patch.object(
                common.time, "sleep", side_effect=sleeps.append
            ):
                first = common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c1"))
                second = common.tts("다른 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "b.wav"), cache_dir=os.path.join(tmp, "c2"))
        self.assertEqual(first, 1.25)
        self.assertEqual(second, 1.25)
        self.assertEqual(state["edge"], len(common.TTS_RATE_LIMIT_DELAYS) + 1)
        self.assertEqual(state["gtts"], 2)
        self.assertEqual(state["openai"], 0)
        self.assertEqual(sleeps, list(common.TTS_RATE_LIMIT_DELAYS))
        self.assertTrue(common._edge_rate_limited)

    def test_gtts_failure_is_the_only_path_to_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"openai": 0}

            def fake_run(cmd):
                if "--write-media" in cmd:
                    raise RuntimeError(_RATE)
                if cmd and cmd[0] == "ffprobe":
                    return "1.0\n"
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".wav"):
                        Path(arg).write_bytes(b"")
                return ""

            def fake_openai(text, voice, rate, pitch, mp3):
                state["openai"] += 1
                Path(mp3).write_bytes(b"mp3")

            env = {"OPENAI_API_KEY": "test-key", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "gtts_tts", side_effect=RuntimeError("gtts down")
            ), patch.object(common, "openai_tts", side_effect=fake_openai), patch.object(
                common.time, "sleep", return_value=None
            ):
                dur = common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertEqual(dur, 1.0)
        self.assertEqual(state["openai"], 1)

    def test_exhausted_429_without_openai_key_uses_gtts(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(cmd):
                if "--write-media" in cmd:
                    raise RuntimeError(_RATE)
                if cmd and cmd[0] == "ffprobe":
                    return "1.1\n"
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".wav"):
                        Path(arg).write_bytes(b"")
                return ""

            def write_mp3(text, voice, rate, pitch, mp3):
                Path(mp3).write_bytes(b"mp3")

            env = {"OPENAI_API_KEY": "", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "gtts_tts", side_effect=write_mp3
            ), patch.object(common, "openai_tts") as openai, patch.object(common.time, "sleep", return_value=None):
                dur = common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertEqual(dur, 1.1)
        openai.assert_not_called()

    def test_exhausted_429_and_gtts_without_openai_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(cmd):
                if "--write-media" in cmd:
                    raise RuntimeError(_RATE)
                return ""

            env = {"OPENAI_API_KEY": "", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "gtts_tts", side_effect=RuntimeError("gtts down")
            ), patch.object(common, "openai_tts") as openai, patch.object(common.time, "sleep", return_value=None):
                with self.assertRaises(RuntimeError) as caught:
                    common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertIn("429", str(caught.exception))
        openai.assert_not_called()

    def test_other_errors_backoff_then_gtts(self):
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            state = {"edge": 0, "gtts": 0}

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

            def fake_gtts(text, voice, rate, pitch, mp3):
                state["gtts"] += 1
                Path(mp3).write_bytes(b"mp3")

            env = {"OPENAI_API_KEY": "test-key", "OPENAI_API_KEY_FIXED": "", "TTS_BACKEND": "edge"}
            with patch.dict(os.environ, env, clear=False), patch.object(common, "run", side_effect=fake_run), patch.object(
                common, "gtts_tts", side_effect=fake_gtts
            ), patch.object(common, "openai_tts") as openai, patch.object(
                common.time, "sleep", side_effect=sleeps.append
            ):
                common.tts("한 문장.", "ko-KR-SunHiNeural", os.path.join(tmp, "a.wav"), cache_dir=os.path.join(tmp, "c"))
        self.assertEqual(state["edge"], len(common.TTS_OTHER_ERROR_DELAYS) + 1)
        self.assertEqual(state["gtts"], 1)
        self.assertEqual(sleeps, list(common.TTS_OTHER_ERROR_DELAYS))
        openai.assert_not_called()
        self.assertFalse(common._edge_rate_limited)

    def test_render_step_does_not_pass_openai_key(self):
        text = Path(__file__).resolve().parents[1].joinpath(".github/workflows/daily_shorts.yml").read_text(encoding="utf-8")
        threads = Path(__file__).resolve().parents[1].joinpath(".github/workflows/daily_threads.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests -b", text)
        render = text.split("대기 사연", 1)[1].split("렌더된 mp4", 1)[0]
        self.assertNotIn("OPENAI_API_KEY", render)
        self.assertNotIn("secrets.OPENAI_API_KEY", text)
        self.assertNotIn("secrets.OPENAI_API_KEY", threads)
        self.assertNotIn("generate_more_stories.py", text)
        self.assertNotIn("generate_more_stories.py", threads)
        self.assertNotIn("refill_queue.py", text)
        self.assertNotIn("refill_queue.py", threads)
        self.assertIn("consume_content_queue.py --channel shorts", text)
        self.assertIn("consume_content_queue.py --channel threads", threads)


if __name__ == "__main__":
    unittest.main()
