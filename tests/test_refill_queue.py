import copy
import json
import unittest
from pathlib import Path

from refill_queue import (
    adjust_spec_to_window,
    check,
    estimate_duration,
    length_retry_message,
    ordered_pending,
    spoken_char_count,
    write_spec,
)


class RefillQueueTest(unittest.TestCase):
    def test_order_matches_make_shorts(self):
        recs = [{"EP": 1, "제목": "a", "YouTube": "완료"}, {"EP": 2, "제목": "b", "YouTube": "대기"},
                {"EP": 3, "제목": "c", "YouTube": "대기"}]
        self.assertEqual([i for i, _ in ordered_pending(recs)], [3, 4])

    def test_banned_words(self):
        spec = {"segments": [{"type": "hook", "text": "대전 " * 130}, {"type": "chat", "text": "x"}, {"type": "key", "text": "x"},
                             {"type": "question", "text": "x"}], "title": "t #Shorts", "description": "창작"}
        self.assertTrue(any("대전" in e for e in check(spec)))

    def test_ep79_passes_length_check(self):
        spec = json.loads((Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep079.json").read_text(encoding="utf-8"))
        self.assertEqual(check(spec), [])

    def test_short_beats_fail_length_estimate(self):
        spec = json.loads((Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep079.json").read_text(encoding="utf-8"))
        for seg in spec["segments"]:
            seg["spoken"] = "짧아요."
            seg.pop("tail", None)
        errs = check(spec)
        self.assertTrue(any("예상 길이" in e for e in errs), errs)
        self.assertIsNone(adjust_spec_to_window(spec))

    def test_near_miss_short_and_long_specs_are_fit_into_the_window(self):
        base = json.loads(
            (Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep080.json").read_text(encoding="utf-8")
        )
        short = copy.deepcopy(base)
        # Drop two narr beats so the estimate falls just under 49s, the way the
        # 2026-10-21 regen ended at 46.7s / 260자.
        removed = 0
        for seg in short["segments"]:
            if seg.get("type") == "narr" and removed < 2:
                seg["text"] = "그날 일은 여기까지였어요."
                seg["spoken"] = "그날 일은 여기까지였어요."
                removed += 1
        self.assertTrue(check(short), check(short))
        fitted = adjust_spec_to_window(short)
        self.assertIsNotNone(fitted)
        self.assertEqual(check(fitted), [])
        self.assertNotEqual(spoken_char_count(short), spoken_char_count(fitted))

        long = copy.deepcopy(base)
        for seg in long["segments"]:
            if seg.get("type") == "narr":
                extra = "예단 목록의 금액이 생각보다 훨씬 컸어요."
                seg["text"] = f"{seg['text']} {extra}"
                seg["spoken"] = f"{seg.get('spoken') or seg['text']}"
                break
        self.assertTrue(any("예상 길이" in e or "읽는 글자" in e for e in check(long)), check(long))
        fitted_long = adjust_spec_to_window(long)
        self.assertIsNotNone(fitted_long)
        self.assertEqual(check(fitted_long), [])
        self.assertLess(estimate_duration(fitted_long), estimate_duration(long))

    def test_retry_message_aims_at_the_middle_when_length_oscillates(self):
        # Numbers from the 2026-10-21 refill of '시댁 가족사진에서 나만 잘렸어요'.
        msg = length_retry_message(
            [(322, 55.7), (241, 43.8)],
            ["읽는 글자 수 241자 (목표 265~330자)", "예상 길이 43.8s (목표 49~53s, 렌더 허용 45~58s). 현재 241자."],
        )
        self.assertIn("반대쪽", msg)
        self.assertIn("약 281자", msg)  # (322 + 241) // 2
        self.assertIn("자만 늘려", msg)

    def test_write_spec_fits_a_near_miss_without_another_model_call(self):
        base = json.loads(
            (Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep080.json").read_text(encoding="utf-8")
        )
        short = copy.deepcopy(base)
        for seg in short["segments"]:
            if seg.get("type") == "narr":
                seg["text"] = "그날 일은 여기까지였어요."
                seg["spoken"] = "그날 일은 여기까지였어요."
                break
        self.assertTrue(check(short))
        client = _FakeClient([short])
        spec = write_spec(client, {"제목": "시댁 가족사진에서 나만 잘렸어요, 결말은?", "사연": "원문"}, None, 84, [{}, {}])
        self.assertEqual(check(spec), [])
        self.assertEqual(client.temperatures, [0.7])
        self.assertGreaterEqual(estimate_duration(spec), 49.0)
        self.assertLessEqual(estimate_duration(spec), 53.0)

    def test_write_spec_lowers_temperature_and_names_the_oscillation(self):
        base = json.loads(
            (Path(__file__).resolve().parents[1] / "sayeon_specs" / "sayeon_ep080.json").read_text(encoding="utf-8")
        )
        long = copy.deepcopy(base)
        for seg in long["segments"]:
            seg["spoken"] = (segment_blob(seg) + " ") * 4
            seg["text"] = seg["spoken"]
        short = copy.deepcopy(base)
        for seg in short["segments"]:
            seg["spoken"] = "너무 짧아요."
            seg["text"] = "너무 짧아요."
            seg.pop("tail", None)
        good = copy.deepcopy(base)
        client = _FakeClient([long, short, good])
        spec = write_spec(client, {"제목": "테스트", "사연": "원문"}, None, 90, [{}, {}])
        self.assertEqual(spec["episode"], 90)
        self.assertEqual(check(spec), [])
        self.assertEqual(client.temperatures, [0.7, 0.2, 0.2])
        feedback = client.messages[2][-1]["content"]
        self.assertIn("반대쪽", feedback)
        self.assertIn("장면을 새로 쓰지 말고", feedback)
        self.assertIn("중간인 약", feedback)
        self.assertIn("늘려", feedback)


def segment_blob(seg: dict) -> str:
    return str(seg.get("spoken") or seg.get("text") or "문장입니다.")


class _FakeClient:
    def __init__(self, payloads: list[dict]):
        self.payloads = [json.dumps(p, ensure_ascii=False) for p in payloads]
        self.temperatures: list[float] = []
        self.messages: list[list] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.temperatures.append(kwargs["temperature"])
        self.messages.append(kwargs["messages"])
        content = self.payloads.pop(0)

        class _Msg:
            def __init__(self, content):
                self.content = content

        class _Choice:
            def __init__(self, content):
                self.message = _Msg(content)

        class _Resp:
            def __init__(self, content):
                self.choices = [_Choice(content)]

        return _Resp(content)


if __name__ == "__main__":
    unittest.main()
