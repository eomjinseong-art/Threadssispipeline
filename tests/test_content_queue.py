"""Committed queue: scheduled runs copy stories, they do not call an LLM."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from consume_content_queue import main as consume_main
from content_queue import (
    EMPTY_LOG,
    MIN_PENDING,
    QUEUE_PATH,
    ROOT,
    STATE_PATH,
    choose_to_append,
    format_inventory,
    inventory,
    item_from_spec,
    load_queue,
    load_state,
    run_consume,
    title_key,
)
from sayeon_render import find_spec_for_title


class ContentQueueTests(unittest.TestCase):
    def test_committed_items_match_specs_and_doc_runway(self):
        items = load_queue(QUEUE_PATH)
        state = load_state(STATE_PATH)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(state["consumed_ids"], [])
        ids = [item["id"] for item in items]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        for item in items:
            path, spec = find_spec_for_title(item["title"])
            self.assertIsNotNone(spec, item["id"])
            self.assertEqual(Path(path).resolve(), (ROOT / item["spec"]).resolve())
            built = item_from_spec(ROOT / item["spec"], spec)
            self.assertEqual(item["id"], built["id"])
            self.assertEqual(title_key(item["title"]), title_key(spec["topic"]))
            self.assertEqual(item["story_lines"], built["story_lines"])
            self.assertTrue(item["question"].endswith("?") or "까요" in item["question"])
        inv = inventory(items, state, ROOT)
        doc = (ROOT / "docs" / "CONTENT_QUEUE.md").read_text(encoding="utf-8")
        line = format_inventory(inv)
        self.assertIn(line, doc)
        self.assertIn(EMPTY_LOG, doc)
        self.assertGreater(inv["shorts_days"], inv["threads_days"])

    def test_empty_queue_skips_without_touching_a_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "queue.json"
            state = Path(tmp) / "state.json"
            queue.write_text(json.dumps({"version": 1, "items": []}), encoding="utf-8")
            state.write_text(json.dumps({"consumed_ids": []}), encoding="utf-8")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = consume_main(["--queue", str(queue), "--state", str(state), "--channel", "threads"])
        self.assertEqual(code, 0)
        self.assertIn(EMPTY_LOG, buf.getvalue())
        self.assertIn("Threads 남은 항목: 0", buf.getvalue())

    def test_missing_queue_file_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = run_consume(
                    queue_path=Path(tmp) / "missing.json",
                    state_path=Path(tmp) / "state.json",
                    sheet_loader=lambda: (_ for _ in ()).throw(AssertionError("sheet")),
                    channel="shorts",
                )
        self.assertEqual(code, 0)
        self.assertIn(EMPTY_LOG, buf.getvalue())

    def test_appends_only_until_pending_is_full_and_skips_titles_already_on_the_sheet(self):
        spec = ROOT / "sayeon_specs" / "sayeon_ep069.json"
        first = item_from_spec(spec)
        second = dict(first, id="ep999", title="새로 넣은 사연, 결말은?")
        items = [first, second]
        records = []
        for ep in range(1, MIN_PENDING):
            records.append({"Status": "대기", "EP": ep, "제목": f"기존 {ep}", "YouTube": "대기"})
        records.append({"Status": "완료", "EP": 69, "제목": first["title"], "YouTube": "완료"})

        class Sheet:
            def __init__(self):
                self.records = [dict(row) for row in records]
                self.appended = []

            def get_all_records(self):
                return list(self.records)

            def append_rows(self, rows, value_input_option=None):
                self.appended.extend(rows)
                for row in rows:
                    self.records.append(
                        {"Status": row[0], "EP": row[1], "제목": row[2], "사연": row[3], "YouTube": ""}
                    )

        sheet = Sheet()
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            queue.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False), encoding="utf-8")
            state_path.write_text(json.dumps({"consumed_ids": []}), encoding="utf-8")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = run_consume(
                    queue_path=queue,
                    state_path=state_path,
                    sheet_loader=lambda: sheet,
                    channel="threads",
                    root=ROOT,
                )
            saved = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(len(sheet.appended), 1)
        self.assertEqual(sheet.appended[0][2], "새로 넣은 사연, 결말은?")
        self.assertEqual(saved["consumed_ids"], ["ep069", "ep999"])
        self.assertNotIn("openai", buf.getvalue().lower())

    def test_stocked_sheet_does_not_consume(self):
        item = item_from_spec(ROOT / "sayeon_specs" / "sayeon_ep070.json")
        records = [
            {"Status": "대기", "EP": ep, "제목": f"대기 {ep}", "YouTube": "대기"}
            for ep in range(1, MIN_PENDING + 2)
        ]
        chosen = choose_to_append(
            [item],
            {"consumed_ids": []},
            threads_pending=MIN_PENDING,
            shorts_pending=MIN_PENDING,
            root=ROOT,
        )
        self.assertEqual(chosen, [])

    def test_scheduled_scripts_refuse_before_any_model_call(self):
        import generate_more_stories
        import refill_queue

        env = {"GITHUB_ACTIONS": "true", "OPENAI_API_KEY": "sk-test", "GEMINI_API_KEY": "gem-test"}
        with patch.dict("os.environ", env, clear=False), patch(
            "generate_more_stories.open_manual_client", side_effect=AssertionError("llm")
        ), patch("generate_more_stories.load_client", side_effect=AssertionError("sheet")):
            generate_more_stories.main()
        with patch.dict("os.environ", env, clear=False), patch(
            "refill_queue.load_records", side_effect=AssertionError("sheet")
        ), patch("refill_queue.open_manual_client", side_effect=AssertionError("llm")):
            self.assertEqual(refill_queue.main(), 0)


class ManualLlmTests(unittest.TestCase):
    def test_gemini_wins_over_openai(self):
        from manual_llm import DEFAULT_GEMINI_MODEL, open_manual_client

        env = {
            "GITHUB_ACTIONS": "",
            "ALLOW_MANUAL_LLM": "",
            "GEMINI_API_KEY": "gem-test",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-4.1-mini",
        }
        with patch.dict("os.environ", env, clear=False):
            client, model = open_manual_client("gpt-4.1-mini", openai_model_env="OPENAI_MODEL")
        self.assertEqual(model, DEFAULT_GEMINI_MODEL)
        self.assertEqual(client.api_key, "gem-test")
        self.assertIn("generativelanguage.googleapis.com", str(client.base_url))

    def test_openai_is_only_the_manual_fallback(self):
        from manual_llm import open_manual_client

        env = {
            "GITHUB_ACTIONS": "",
            "ALLOW_MANUAL_LLM": "",
            "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_API_KEY_FIXED": "",
            "OPENAI_SPEC_MODEL": "gpt-4.1",
        }
        with patch.dict("os.environ", env, clear=False):
            client, model = open_manual_client("gpt-4.1-mini", openai_model_env="OPENAI_SPEC_MODEL")
        self.assertEqual(model, "gpt-4.1")
        self.assertEqual(client.api_key, "sk-test")

    def test_actions_cannot_open_a_client(self):
        from manual_llm import ScheduledLlmBlocked, open_manual_client

        env = {"GITHUB_ACTIONS": "true", "GEMINI_API_KEY": "gem-test", "ALLOW_MANUAL_LLM": ""}
        with patch.dict("os.environ", env, clear=False):
            with self.assertRaises(ScheduledLlmBlocked):
                open_manual_client("gpt-4.1-mini", openai_model_env="OPENAI_MODEL")


if __name__ == "__main__":
    unittest.main()
