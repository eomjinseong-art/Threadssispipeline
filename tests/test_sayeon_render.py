import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sayeon_render import SPECS_DIR, find_spec_for_title, load_specs, topic_key, validate_spec


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


if __name__ == "__main__":
    unittest.main()
