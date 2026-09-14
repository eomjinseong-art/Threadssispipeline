"""
1일 1쇼츠 자동화 파이프라인 - YouTube 업로드 + 썸네일 + 홍보 댓글

assemble_video.py가 만든 output/final_row{N}.mp4 를 YouTube Shorts로 업로드한다.
업로드 직후 홍보용 댓글을 달고, 커스텀 썸네일을 지정한다.

헤드리스(GitHub Actions) 인증:
  YOUTUBE_TOKEN_JSON 을 token.json 으로 쓰고,
  필요하면 YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_SECRET_JSON 으로 갱신한다.
  CI에서는 브라우저 OAuth를 열지 않는다.

채널 검증:
  EXPECTED_YOUTUBE_CHANNEL_ID 가 있으면 불일치 시 업로드를 중단한다.
  없으면 경고만 하고 진행한다 (시크릿이 아직 없을 수 있음).
  과거 사고(그날의남녀, Feedscanai)처럼 잘못된 채널에 조용히 올라가는 것을 막는다.

스레드 포스팅과 시트 완료 표시는 이 모듈이 하지 않는다. make_shorts.py 가
YouTube 성공 후에만 처리한다.

필요 환경변수:
  YOUTUBE_TOKEN_JSON
  YOUTUBE_REFRESH_TOKEN          (선택 - token에 refresh가 없을 때)
  YOUTUBE_CLIENT_SECRET_JSON     (선택 - client_id/secret 보강)
  EXPECTED_YOUTUBE_CHANNEL_ID    (선택 - 없으면 경고 후 계속)
  SLACK_WEBHOOK_URL              (선택)
"""

from __future__ import annotations

import argparse
import json
import os
import textwrap

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw

from shorts_style import get_font, thumbnail_path_for_row

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_SECRET_PATH = "client_secret.json"
TOKEN_PATH = "token.json"

HASHTAGS = "#Shorts #사연 #고민상담 #카톡썰 #언니들 #사이다"
SCHEDULE_NOTE = "매일 오전 9시 · 오후 6시 · 오후 9시 새 사연 올라옵니다"
PINNED_COMMENT_TEMPLATE = (
    "오늘 사연 어떠셨나요? 여러분이라면 어떻게 하셨을 것 같아요? 👇\n"
    "비슷한 사연 있으면 댓글로 남겨주세요, 다음 에피소드 소재로 쓸 수도 있어요!\n"
    "매일 오전 9시·오후 6시·오후 9시 새 사연 올라옵니다 🔔"
)

THUMBNAIL_SIZE = (1280, 720)
TITLE_MAX_LEN = 100
THREADS_API_BASE = "https://graph.threads.net/v1.0"
THREADS_MAX_CHARS = 500


def _is_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def _parse_json_env(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        return {}
    return json.loads(text)


def write_auth_files_from_env(
    token_path: str = TOKEN_PATH,
    client_secret_path: str = CLIENT_SECRET_PATH,
) -> None:
    """GitHub Actions 시크릿을 token.json / client_secret.json 으로 복원한다."""
    token_raw = os.environ.get("YOUTUBE_TOKEN_JSON", "").strip()
    client_raw = os.environ.get("YOUTUBE_CLIENT_SECRET_JSON", "").strip()
    refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()

    client_info: dict = {}
    if client_raw:
        with open(client_secret_path, "w", encoding="utf-8") as f:
            f.write(client_raw)
        try:
            client_info = json.loads(client_raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"YOUTUBE_CLIENT_SECRET_JSON 이 올바른 JSON이 아닙니다: {exc}") from exc

    installed = {}
    if isinstance(client_info, dict):
        installed = client_info.get("installed") or client_info.get("web") or {}

    token_data: dict = {}
    if token_raw:
        try:
            parsed = json.loads(token_raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"YOUTUBE_TOKEN_JSON 이 올바른 JSON이 아닙니다: {exc}") from exc
        if isinstance(parsed, dict):
            token_data = parsed

    if refresh:
        token_data["refresh_token"] = refresh

    if installed.get("client_id"):
        token_data.setdefault("client_id", installed["client_id"])
    if installed.get("client_secret"):
        token_data.setdefault("client_secret", installed["client_secret"])
    token_data.setdefault("token_uri", installed.get("token_uri") or "https://oauth2.googleapis.com/token")

    if token_data.get("refresh_token") or token_data.get("token"):
        with open(token_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f)


def get_credentials(
    token_path: str = TOKEN_PATH,
    client_secret_path: str = CLIENT_SECRET_PATH,
) -> Credentials:
    write_auth_files_from_env(token_path=token_path, client_secret_path=client_secret_path)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    if _is_ci():
        raise SystemExit(
            "헤드리스 환경에서 YouTube 인증에 실패했습니다. "
            "YOUTUBE_TOKEN_JSON (및 필요 시 YOUTUBE_REFRESH_TOKEN, "
            "YOUTUBE_CLIENT_SECRET_JSON) 시크릿을 확인하세요. "
            "로컬에서 python reauth_youtube.py 로 token.json 을 다시 발급하면 됩니다."
        )

    if not os.path.exists(client_secret_path):
        raise SystemExit(
            f"{client_secret_path} 가 없습니다. Google Cloud Console에서 "
            "OAuth 클라이언트를 만들고 다운로드한 파일을 이 경로에 두세요. "
            "또는 python reauth_youtube.py 를 실행하세요."
        )
    print("최초 1회 인증이 필요합니다. 브라우저가 열립니다...")
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def verify_channel(creds: Credentials) -> dict | None:
    """토큰이 EXPECTED_YOUTUBE_CHANNEL_ID 채널인지 확인한다.

    환경변수가 없으면 경고 후 None을 반환하고 업로드를 계속한다.
    불일치면 SystemExit로 업로드를 중단한다.
    """
    expected_id = (os.environ.get("EXPECTED_YOUTUBE_CHANNEL_ID") or "").strip()
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise SystemExit("이 토큰으로 연결된 채널을 찾을 수 없습니다.")

    actual_id = items[0]["id"]
    actual_title = items[0]["snippet"]["title"]
    info = {"id": actual_id, "title": actual_title}

    if not expected_id:
        print(
            "  [경고] EXPECTED_YOUTUBE_CHANNEL_ID가 설정되지 않아 채널 검증을 건너뜁니다. "
            f"현재 인증된 채널: '{actual_title}' (ID: {actual_id}). "
            "잘못된 채널(그날의남녀, Feedscanai 등)에 업로드될 위험이 있으니 설정을 권장합니다."
        )
        return info

    if actual_id != expected_id:
        raise SystemExit(
            f"채널 불일치! 기대한 채널 ID: {expected_id} / "
            f"실제 인증된 채널: '{actual_title}' (ID: {actual_id}). "
            "잘못된 계정으로 인증됐을 가능성이 높습니다. 업로드를 중단합니다. "
            "reauth_youtube.py를 다시 실행해서 정확한 채널로 재인증하세요."
        )

    print(f"  채널 확인 완료: '{actual_title}' (일치)")
    return info


def _story_and_question(script: dict) -> tuple[str, str]:
    slides = script.get("slides") or []
    story = ""
    question = ""
    for slide in slides:
        if slide.get("type") == "story":
            story = str(slide.get("display_text") or "").replace("\n", " ")
        elif slide.get("type") == "question":
            question = str(slide.get("display_text") or "").strip()
    if not story and script.get("turns"):
        story = " ".join(
            t["line"] for t in script["turns"] if t.get("speaker") == "reporter"
        )
        question = next(
            (t["line"] for t in script["turns"] if t.get("speaker") == "question"),
            "",
        )
    return story, question


def shorts_title(raw_title: str) -> str:
    title = (raw_title or "언니들의 사연").strip()
    if "#Shorts" not in title and "#shorts" not in title.lower():
        suffix = " #Shorts"
        if len(title) + len(suffix) <= TITLE_MAX_LEN:
            title = title + suffix
    return title[:TITLE_MAX_LEN]


def build_metadata(script: dict) -> dict:
    title = shorts_title(script.get("title") or "언니들의 사연")
    story_summary, question = _story_and_question(script)
    if len(story_summary) > 300:
        story_summary = story_summary[:297] + "..."

    description = (
        f"{story_summary}\n\n"
        f"{question}\n\n"
        "여러분 생각은 댓글로 알려주세요 👇\n"
        f"{SCHEDULE_NOTE}\n\n"
        f"{HASHTAGS}"
    )
    tags = ["Shorts", "사연", "고민상담", "카톡썰", "언니들", "사이다", "썰", "인간관계"]
    return {"title": title, "description": description, "tags": tags}


def build_thumbnail(title: str, out_path: str) -> None:
    img = Image.new("RGB", THUMBNAIL_SIZE, color=(10, 10, 10))
    draw = ImageDraw.Draw(img)
    font = get_font(72)
    wrapped_lines = textwrap.wrap(title.replace(" #Shorts", ""), width=18)

    line_heights = []
    for line in wrapped_lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
    line_spacing = 16
    total_height = sum(line_heights) + line_spacing * max(0, len(wrapped_lines) - 1)

    y = (THUMBNAIL_SIZE[1] - total_height) // 2
    for line, h in zip(wrapped_lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (THUMBNAIL_SIZE[0] - w) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += h + line_spacing

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)


def set_thumbnail(creds: Credentials, video_id: str, thumbnail_path: str) -> None:
    youtube = build("youtube", "v3", credentials=creds)
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
        ).execute()
    except Exception as e:
        print(f"  [경고] 썸네일 설정 실패 (채널 전화번호 인증이 안 되어 있을 수 있습니다): {e}")


def post_pinned_style_comment(creds: Credentials, video_id: str, text: str) -> None:
    youtube = build("youtube", "v3", credentials=creds)
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                }
            },
        ).execute()
        print(
            "  댓글 게시 완료. ※ 상단 고정은 유튜브 스튜디오에서 직접 눌러주세요"
            " (API로 자동 고정은 지원되지 않습니다)."
        )
    except Exception as e:
        print(f"  [경고] 댓글 게시 실패 (force-ssl 스코프로 재인증이 필요할 수 있습니다): {e}")


def upload_video(creds: Credentials, video_path: str, metadata: dict) -> str:
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  업로드 진행률: {int(status.progress() * 100)}%")
    return response["id"]


def build_threads_text(script: dict, video_id: str | None = None) -> str:
    """업로드 성공 후 스레드 홍보 문구. 실패해도 호출측에서 무시한다."""
    title = script.get("title") or "언니들의 사연"
    _story, question = _story_and_question(script)
    parts = [title, "", question]
    if video_id:
        parts.extend(["", f"https://youtube.com/shorts/{video_id}"])
    text = "\n".join(p for p in parts if p is not None)
    if len(text) <= THREADS_MAX_CHARS:
        return text
    return text[: THREADS_MAX_CHARS - 3] + "..."


def post_to_threads(text: str) -> None:
    access_token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not access_token or not user_id:
        print("  [안내] THREADS_ACCESS_TOKEN/THREADS_USER_ID 없음 - 스레드 포스팅 건너뜀.")
        return

    try:
        create_resp = requests.post(
            f"{THREADS_API_BASE}/{user_id}/threads",
            data={"media_type": "TEXT", "text": text, "access_token": access_token},
            timeout=30,
        )
        create_data = create_resp.json()
        if "id" not in create_data:
            print(f"  [경고] 스레드 컨테이너 생성 실패: {create_data}")
            return

        publish_resp = requests.post(
            f"{THREADS_API_BASE}/{user_id}/threads_publish",
            data={"creation_id": create_data["id"], "access_token": access_token},
            timeout=30,
        )
        publish_data = publish_resp.json()
        if "id" not in publish_data:
            print(f"  [경고] 스레드 퍼블리시 실패: {publish_data}")
            return

        print(f"  스레드 게시 완료 (게시물 ID: {publish_data['id']})")
    except Exception as e:
        print(f"  [경고] 스레드 포스팅 중 오류(무시하고 계속): {e}")


def notify_failure(stage: str, error: Exception) -> None:
    message = f":rotating_light: 쇼츠 자동화 파이프라인 실패 - [{stage}] {error}"
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    print(message)
    if webhook_url:
        try:
            requests.post(webhook_url, json={"text": message}, timeout=10)
        except Exception as e:
            print(f"  Slack 알림 전송도 실패했습니다: {e}")


def upload_short(video_path: str, script_path: str) -> str:
    """명시된 mp4 + script JSON을 Shorts로 업로드하고 video_id를 반환한다.

    시트 완료 표시/스레드 포스팅은 하지 않는다.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"영상 파일이 없습니다: {video_path}")
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"스크립트가 없습니다: {script_path}")

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    print("[1/5] YouTube 인증 중...")
    creds = get_credentials()

    print("[2/5] 채널 확인 중...")
    verify_channel(creds)

    print("[3/5] 메타데이터(제목/설명/태그) 생성 중...")
    metadata = build_metadata(script)
    print(f"  제목: {metadata['title']}")

    print("[4/5] 업로드 중...")
    video_id = upload_video(creds, video_path, metadata)

    print("[5/5] 썸네일/댓글 (실패해도 업로드는 유지)...")
    row_index = script.get("row_index", "local")
    thumbnail_path = thumbnail_path_for_row(row_index)
    try:
        build_thumbnail(script.get("title", metadata["title"]), thumbnail_path)
        set_thumbnail(creds, video_id, thumbnail_path)
    except Exception as e:
        print(f"  [경고] 썸네일 처리 실패: {e}")
    post_pinned_style_comment(creds, video_id, PINNED_COMMENT_TEMPLATE)

    print(f"완료: https://youtube.com/shorts/{video_id}")
    return video_id


def main() -> None:
    parser = argparse.ArgumentParser(description="이미 만든 Shorts mp4를 YouTube에 올립니다.")
    parser.add_argument("--video", required=True, help="output/final_rowN.mp4")
    parser.add_argument("--script", required=True, help="output/script_rowN.json")
    args = parser.parse_args()
    try:
        upload_short(args.video, args.script)
    except Exception as e:
        notify_failure(stage="upload_video", error=e)
        raise


if __name__ == "__main__":
    main()
