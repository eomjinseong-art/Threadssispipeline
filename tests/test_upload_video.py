import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from upload_video import (
    build_metadata,
    build_threads_text,
    get_credentials,
    parse_first_json_value,
    shorts_title,
    verify_channel,
    write_auth_files_from_env,
)


def _script():
    return {
        "title": "EP.40 외모를 평가하는 남편",
        "slides": [
            {"type": "story", "display_text": "남편이 외모를 평가해요."},
            {"type": "question", "display_text": "여러분이라면 어떻게 하겠어요?"},
        ],
    }


class _FakeChannels:
    def __init__(self, channel_id: str, title: str):
        self.channel_id = channel_id
        self.title = title

    def list(self, **_kwargs):
        return self

    def execute(self):
        return {"items": [{"id": self.channel_id, "snippet": {"title": self.title}}]}


class _FakeYoutube:
    def __init__(self, channel_id: str, title: str):
        self._channels = _FakeChannels(channel_id, title)

    def channels(self):
        return self._channels


class UploadHelperTests(unittest.TestCase):
    def test_metadata_is_korean_shorts_friendly(self):
        meta = build_metadata(_script())
        self.assertIn("#Shorts", meta["title"])
        self.assertIn("#Shorts", meta["description"])
        self.assertIn("남편이 외모를 평가해요.", meta["description"])
        self.assertIn("여러분이라면 어떻게 하겠어요?", meta["description"])
        self.assertIn("Shorts", meta["tags"])

    def test_shorts_title_stays_within_limit(self):
        title = shorts_title("가" * 120)
        self.assertLessEqual(len(title), 100)

    def test_write_auth_files_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            secret_path = Path(tmp) / "client_secret.json"
            env = {
                "YOUTUBE_TOKEN_JSON": json.dumps({"token": "ya29.old", "refresh_token": "old-rt"}),
                "YOUTUBE_REFRESH_TOKEN": "new-rt",
                "YOUTUBE_CLIENT_SECRET_JSON": json.dumps({
                    "installed": {
                        "client_id": "cid.apps.googleusercontent.com",
                        "client_secret": "csec",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }),
            }
            with patch.dict(os.environ, env, clear=False):
                write_auth_files_from_env(str(token_path), str(secret_path))
            token = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(token["refresh_token"], "new-rt")
            self.assertEqual(token["token"], "ya29.old")
            self.assertEqual(token["client_id"], "cid.apps.googleusercontent.com")
            self.assertTrue(secret_path.is_file())

    def test_client_secret_trailing_extra_data_does_not_raise(self):
        """Actions 시크릿에 JSON 객체 + 뒤 텍스트가 붙어 Extra data 가 나던 경우."""
        secret_obj = {
            "installed": {
                "client_id": "cid.apps.googleusercontent.com",
                "client_secret": "csec",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        trailing = json.dumps(secret_obj, indent=2) + "\n\n# pasted note\n{\"extra\": true}\n"
        self.assertIsInstance(parse_first_json_value(trailing), dict)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(trailing)

        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            secret_path = Path(tmp) / "client_secret.json"
            env = {
                "YOUTUBE_TOKEN_JSON": json.dumps({"token": "ya29.ok", "refresh_token": "rt"}),
                "YOUTUBE_REFRESH_TOKEN": "rt-backup",
                "YOUTUBE_CLIENT_SECRET_JSON": trailing,
            }
            with patch.dict(os.environ, env, clear=False):
                write_auth_files_from_env(str(token_path), str(secret_path))
            token = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(token["token"], "ya29.ok")
            self.assertEqual(token["refresh_token"], "rt-backup")
            self.assertEqual(token["client_id"], "cid.apps.googleusercontent.com")
            written_secret = json.loads(secret_path.read_text(encoding="utf-8"))
            self.assertEqual(written_secret["installed"]["client_id"], "cid.apps.googleusercontent.com")

    def test_unparseable_client_secret_warns_and_keeps_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            secret_path = Path(tmp) / "client_secret.json"
            env = {
                "YOUTUBE_TOKEN_JSON": json.dumps({"token": "ya29.ok", "refresh_token": "rt"}),
                "YOUTUBE_CLIENT_SECRET_JSON": "not-json-at-all <<<",
            }
            with patch.dict(os.environ, env, clear=False):
                write_auth_files_from_env(str(token_path), str(secret_path))
            token = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(token["token"], "ya29.ok")
            self.assertFalse(secret_path.exists())

    def test_headless_without_token_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "missing-token.json"
            secret_path = Path(tmp) / "missing-secret.json"
            env = {
                "CI": "true",
                "GITHUB_ACTIONS": "true",
                "YOUTUBE_TOKEN_JSON": "",
                "YOUTUBE_REFRESH_TOKEN": "",
                "YOUTUBE_CLIENT_SECRET_JSON": "",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(SystemExit) as ctx:
                    get_credentials(str(token_path), str(secret_path))
            self.assertIn("헤드리스", str(ctx.exception))

    @patch("upload_video.build")
    def test_channel_mismatch_aborts(self, mock_build):
        mock_build.return_value = _FakeYoutube("UC_WRONG", "그날의남녀")
        with patch.dict(os.environ, {"EXPECTED_YOUTUBE_CHANNEL_ID": "UC_EXPECTED"}, clear=False):
            with self.assertRaises(SystemExit) as ctx:
                verify_channel(MagicMock())
        self.assertIn("채널 불일치", str(ctx.exception))
        self.assertIn("그날의남녀", str(ctx.exception))

    @patch("upload_video.build")
    def test_channel_match_continues(self, mock_build):
        mock_build.return_value = _FakeYoutube("UC_OK", "언니들")
        with patch.dict(os.environ, {"EXPECTED_YOUTUBE_CHANNEL_ID": "UC_OK"}, clear=False):
            info = verify_channel(MagicMock())
        self.assertEqual(info["id"], "UC_OK")

    @patch("upload_video.build")
    def test_unset_expected_channel_warns_and_continues(self, mock_build):
        mock_build.return_value = _FakeYoutube("UC_ANY", "언니들")
        env = os.environ.copy()
        env.pop("EXPECTED_YOUTUBE_CHANNEL_ID", None)
        with patch.dict(os.environ, env, clear=True):
            info = verify_channel(MagicMock())
        self.assertEqual(info["id"], "UC_ANY")

    def test_threads_promo_includes_short_url(self):
        text = build_threads_text(_script(), video_id="abc123")
        self.assertIn("EP.40", text)
        self.assertIn("https://youtube.com/shorts/abc123", text)


if __name__ == "__main__":
    unittest.main()
