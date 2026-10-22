import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sayeon_render import (
    ESTIMATE_RANGE,
    SPECS_DIR,
    DurationOutOfRange,
    estimate_duration,
    find_spec_for_title,
    load_specs,
    topic_key,
    validate_spec,
)

# daily-shorts-pipeline 2026-10-15~18 에 실제로 렌더된 길이(초).
# 추정기는 음성 모델 상수라, 이 네 편에서 3.6초 넘게 어긋나면 상수가 바뀐 것이다.
CI_RENDERED_SECONDS = {75: 54.5, 76: 45.2, 77: 53.1, 78: 55.1}


class SayeonSpecTests(unittest.TestCase):
    def test_every_committed_spec_is_ep67_shape(self):
        specs = load_specs()
        self.assertTrue(specs)
        for path, spec in specs:
            with self.subTest(path=path):
                validate_spec(spec)
                self.assertTrue(spec["label"].startswith("오늘의 사연 · EP."))

    def test_reference_ep67_is_valid(self):
        specs = load_specs(str(Path(SPECS_DIR) / "reference"))
        self.assertEqual(len(specs), 2)
        for _path, spec in specs:
            validate_spec(spec)

    def test_matches_sheet_title_with_or_without_curiosity_suffix(self):
        path, spec = find_spec_for_title("내 적금 깨서 시동생 차 사 준 남편, 결말은?")
        self.assertIsNotNone(spec)
        self.assertEqual(spec["episode"], 73)
        _p, spec2 = find_spec_for_title("내 적금 깨서 시동생 차 사 준 남편")
        self.assertEqual(spec2["episode"], 73)

    def test_unknown_title_has_no_spec(self):
        self.assertEqual(find_spec_for_title("없는 사연 제목"), (None, None))
        self.assertEqual(topic_key(""), "")

    def test_estimate_tracks_rendered_episodes(self):
        by_ep = {spec["episode"]: spec for _path, spec in load_specs()}
        for ep, actual in CI_RENDERED_SECONDS.items():
            est = estimate_duration(by_ep[ep])
            self.assertLess(abs(est - actual), 3.6, f"EP.{ep} est {est:.2f} actual {actual}")

    def test_ep80_next_upload_estimates_inside_render_window(self):
        """2026-10-21 run started EP.80 and stopped on a TTS 429, before the length check."""
        by_ep = {spec["episode"]: spec for _path, spec in load_specs()}
        est = estimate_duration(by_ep[80])
        self.assertGreaterEqual(est, 45.0, est)
        self.assertLessEqual(est, 58.0, est)
        self.assertGreaterEqual(est, ESTIMATE_RANGE[0], est)
        self.assertLessEqual(est, ESTIMATE_RANGE[1], est)

    def test_ep79_estimate_stays_inside_window(self):
        """EP.79 uploaded on 2026-10-20. 42.9s is the pre-fix render, kept only as a test double."""
        by_ep = {spec["episode"]: spec for _path, spec in load_specs()}
        est = estimate_duration(by_ep[79])
        self.assertGreaterEqual(est, ESTIMATE_RANGE[0], est)
        self.assertLessEqual(est, ESTIMATE_RANGE[1], est)
        self.assertNotAlmostEqual(est, 42.9, delta=1.0)

    def test_pending_specs_estimate_inside_generation_window(self):
        lo, hi = ESTIMATE_RANGE
        pending = [spec for _path, spec in load_specs() if spec["episode"] >= 79]
        self.assertEqual(sorted(spec["episode"] for spec in pending), [79, 80, 81])
        for spec in pending:
            est = estimate_duration(spec)
            self.assertGreaterEqual(est, lo, spec["episode"])
            self.assertLessEqual(est, hi, spec["episode"])

    def test_duration_error_names_the_window(self):
        err = DurationOutOfRange(42.9)
        self.assertIsInstance(err, ValueError)
        self.assertEqual(err.total, 42.9)
        self.assertIn("42.9s", str(err))
        self.assertIn("45~58", str(err))


if __name__ == "__main__":
    unittest.main()
