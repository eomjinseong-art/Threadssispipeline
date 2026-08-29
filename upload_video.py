"""
1일 1쇼츠 자동화 파이프라인 - 7단계: YouTube 업로드 + 모니터링 + 스레드 동시 포스팅

assemble_video.py가 만든 output/final_{date}.mp4 를 YouTube Shorts로 업로드하고,
제목/설명/태그를 자동 생성한다. 업로드 직후 홍보용 댓글을 자동으로 달아준다.
유튜브 업로드가 "성공한 경우에만" 같은 회차 나레이션을 스레드(Threads)에도
그대로 올린다(영상 링크는 넣지 않음 - 사용자 요청).
실패 시 Slack(또는 지정한 웹훅)으로 알림을 보낸다.

[수정 1] 날짜를 dt.date.today()로 새로 계산하지 않는다. output/final_*.mp4 를
직접 찾아서 그 파일명에서 날짜를 읽어온다 (build/upload job 시점 어긋남 방지).

[수정 2] build_metadata()가 언니삼총사 사연(한국어) turns 구조에 맞게 제목/설명/
태그를 생성하도록 재작성. 설명에 댓글 유도 문구 + 업로드 스케줄 안내 포함.

[수정 3] 업로드 직후 홍보용 댓글을 자동으로 하나 게시한다(commentThreads.insert).
주의: YouTube Data API는 댓글 게시까지만 지원하고, 댓글을 상단에 "고정"하는
기능은 API로 제공되지 않는다(2026년 기준 공식 미지원). 고정은 유튜브 스튜디오에서
사람이 직접 눌러야 한다 - 이 스크립트는 게시까지만 자동화하고, 고정하라는
안내 메시지를 콘솔에 출력한다.
댓글 게시에는 youtube.force-ssl 스코프가 필요하다. 기존에 youtube.upload +
youtube.readonly 스코프로만 인증했다면, 이 스코프가 없어서 댓글 게시가
실패할 수 있다(업로드 자체는 영향 없음, 댓글만 실패하고 넘어감) - 그 경우
reauth_youtube.py를 force-ssl 스코프 포함 버전으로 다시 실행해서 재인증 필요.

[수정 4] 유튜브 업로드가 성공한 "직후에만" 스레드에도 글을 올린다. 같은
스크립트/같은 실행 흐름 안에서 처리해서, 유튜브 업로드가 실패했는데
스레드에만 먼저 글이 나가는 상황이 생기지 않게 한다. 글 내용은 script.json의
narration(팟캐스트 낭독 원문)을 그대로 옮기고 별도로 다시 쓰지 않는다.
영상 링크는 포함하지 않는다(사용자 요청). 스레드 게시가 실패해도 유튜브
업로드 자체는 이미 끝난 뒤라 예외를 던지지 않고 경고만 출력한다.

[수정 5] 업로드 전에 반드시 채널 ID를 검증한다(EXPECTED_YOUTUBE_CHANNEL_ID 환경변수).
과거 인증 화면에서 다른 브랜드 계정을 잘못 선택해 엉뚱한 채널(그날의남녀,
Feedscanai 등)에 영상이 조용히 올라간 사고가 여러 번 있었다. 이걸 막기 위해,
지금 인증된 토큰이 실제로 이 채널 ID를 가리키는지 API로 직접 확인하고,
안 맞으면 업로드 자체를 하지 않고 즉시 에러로 중단한다("조용히 잘못 올라감"을
"크게 실패함"으로 바꿔서 사고를 원천 차단).

사전 준비물 (1회성, 사람이 직접 해야 하는 부분):
  1. Google Cloud Console에서 프로젝트 생성 -> YouTube Data API v3 활성화
  2. OAuth 2.0 클라이언트 ID 생성 -> client_secret.json 다운로드
  3. reauth_youtube.py를 로컬에서 한 번 실행해서 브라우저 인증을 완료하면
     token.json이 생성됨 (refresh token 포함)
  4. token.json을 GitHub Actions 시크릿(YOUTUBE_TOKEN_JSON)으로 등록
  5. reauth_threads.py로 스레드 인증을 완료하면 threads_token.json이 생성됨
  6. 그 안의 access_token/user_id를 GitHub Secret(THREADS_ACCESS_TOKEN,
     THREADS_USER_ID)으로 등록

필요 환경변수:
  SLACK_WEBHOOK_URL      (선택 - 실패 알림용. 없으면 콘솔에만 출력)
  THREADS_ACCESS_TOKEN   (선택 - 없으면 스레드 포스팅은 건너뜀)
  THREADS_USER_ID        (선택 - 없으면 스레드 포스팅은 건너뜀)

필요 패키지:
  pip install google-auth-oauthlib google-api-python-client Pillow requests --break-system-packages
"""

import os
import re
import glob
import json
import textwrap

import requests
from PIL import Image, ImageDraw, ImageFont
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

THREADS_API_BASE = "https://graph.threads.net/v1.0"
THREADS_MAX_CHARS = 500

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # 댓글 게시에 필요
]

CLIENT_SECRET_PATH = "client_secret.json"
TOKEN_PATH = "token.json"

FINAL_VIDEO_PATH_TEMPLATE = "output/final_{date}.mp4"
SCRIPT_PATH_TEMPLATE = "output/script_{date}.json"
THUMBNAIL_PATH_TEMPLATE = "output/thumbnail_{date}.png"

HASHTAGS = "#사연 #고민상담 #카톡썰 #언니들 #사이다"

SCHEDULE_NOTE = "매일 오전 9시 · 오후 6시 · 오후 9시 새 사연 올라옵니다"

PINNED_COMMENT_TEMPLATE = (
    "오늘 사연 어떠셨나요? 여러분이라면 어떻게 하셨을 것 같아요? 👇\n"
    "비슷한 사연 있으면 댓글로 남겨주세요, 다음 에피소드 소재로 쓸 수도 있어요!\n"
    "매일 오전 9시·오후 6시·오후 9시 새 사연 올라옵니다 🔔"
)

THUMBNAIL_SIZE = (1280, 720)  # 유튜브 권장 썸네일 해상도
FONT_PATH_CANDIDATES = [
    "assets/subtitle.ttf",
    "assets/fonts/subtitle.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


# ---------------------------------------------------------------------------
# 날짜/파일 찾기
# ---------------------------------------------------------------------------

def find_latest_date() -> str:
    paths = glob.glob(FINAL_VIDEO_PATH_TEMPLATE.format(date="*"))
    dates = []
    for p in paths:
        m = re.search(r"final_(\d{4}-\d{2}-\d{2})\.mp4$", os.path.basename(p))
        if m:
            dates.append(m.group(1))
    if not dates:
        raise FileNotFoundError(
            "output/final_*.mp4 파일을 찾을 수 없습니다. "
            "assemble_video.py를 먼저 실행했는지, artifact가 정상적으로 전달됐는지 확인하세요."
        )
    return sorted(dates)[-1]


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_PATH):
                raise SystemExit(
                    f"{CLIENT_SECRET_PATH} 가 없습니다. Google Cloud Console에서 "
                    "OAuth 클라이언트를 만들고 다운로드한 파일을 이 경로에 두세요."
                )
            print("최초 1회 인증이 필요합니다. 브라우저가 열립니다...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def verify_channel(creds: Credentials) -> None:
    """업로드 전에 이 토큰이 정확히 원하는 채널(EXPECTED_YOUTUBE_CHANNEL_ID)을
    가리키는지 확인한다. 안 맞으면 즉시 중단 - 조용히 잘못 올라가는 사고를 막는다."""
    expected_id = os.environ.get("EXPECTED_YOUTUBE_CHANNEL_ID")
    if not expected_id:
        print("  [경고] EXPECTED_YOUTUBE_CHANNEL_ID가 설정되지 않아 채널 검증을 건너뜁니다. "
              "잘못된 채널에 업로드될 위험이 있으니 설정을 권장합니다.")
        return

    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise SystemExit("이 토큰으로 연결된 채널을 찾을 수 없습니다.")

    actual_id = items[0]["id"]
    actual_title = items[0]["snippet"]["title"]

    if actual_id != expected_id:
        raise SystemExit(
            f"채널 불일치! 기대한 채널 ID: {expected_id} / "
            f"실제 인증된 채널: '{actual_title}' (ID: {actual_id}). "
            "잘못된 계정으로 인증됐을 가능성이 높습니다. 업로드를 중단합니다. "
            "reauth_youtube.py를 다시 실행해서 정확한 채널로 재인증하세요."
        )

    print(f"  채널 확인 완료: '{actual_title}' (일치)")


# ---------------------------------------------------------------------------
# 제목/설명/태그 자동 생성 (언니삼총사 사연 콘텐츠용)
# ---------------------------------------------------------------------------

def build_metadata(script: dict) -> dict:
    title = script.get("title") or "언니들의 사연"

    story_lines = [t["line"] for t in script["turns"] if t["speaker"] == "reporter"]
    story_summary = " ".join(story_lines)
    if len(story_summary) > 300:
        story_summary = story_summary[:297] + "..."

    question = next((t["line"] for t in script["turns"] if t["speaker"] == "question"), "")

    description = (
        f"{story_summary}\n\n"
        f"{question}\n\n"
        "여러분 생각은 댓글로 알려주세요 👇\n"
        f"{SCHEDULE_NOTE}\n\n"
        f"{HASHTAGS}"
    )

    tags = ["사연", "고민상담", "카톡썰", "언니들", "사이다", "썰", "인간관계"]

    return {"title": title, "description": description, "tags": tags}


# ---------------------------------------------------------------------------
# 썸네일 생성 (제목 텍스트를 이미지로 렌더링)
# ---------------------------------------------------------------------------

def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATH_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit(
        "썸네일용 한글 폰트를 찾을 수 없습니다. assets/subtitle.ttf 가 있는지 확인하세요."
    )


def build_thumbnail(title: str, out_path: str) -> None:
    img = Image.new("RGB", THUMBNAIL_SIZE, color=(10, 10, 10))
    draw = ImageDraw.Draw(img)

    font = load_font(size=72)
    wrapped_lines = textwrap.wrap(title, width=18)

    line_heights = []
    for line in wrapped_lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
    line_spacing = 16
    total_height = sum(line_heights) + line_spacing * (len(wrapped_lines) - 1)

    y = (THUMBNAIL_SIZE[1] - total_height) // 2
    for line, h in zip(wrapped_lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (THUMBNAIL_SIZE[0] - w) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += h + line_spacing

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)


def set_thumbnail(creds: Credentials, video_id: str, thumbnail_path: str) -> None:
    """업로드된 영상에 커스텀 썸네일을 지정한다.
    주의: 커스텀 썸네일 설정은 채널이 전화번호 인증(phone verification)을
    완료한 경우에만 가능하다. 안 되어 있으면 조용히 건너뛴다."""
    youtube = build("youtube", "v3", credentials=creds)
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
        ).execute()
    except Exception as e:
        print(f"  [경고] 썸네일 설정 실패 (채널 전화번호 인증이 안 되어 있을 수 있습니다): {e}")


# ---------------------------------------------------------------------------
# 홍보용 댓글 자동 게시 (고정은 API 미지원 - 수동 필요)
# ---------------------------------------------------------------------------

def post_pinned_style_comment(creds: Credentials, video_id: str, text: str) -> None:
    """업로드된 영상에 홍보용 댓글을 게시한다. 상단 고정은 YouTube Data API로
    지원되지 않아서 자동화할 수 없다 - 게시까지만 하고, 고정은 사람이 유튜브
    스튜디오에서 직접 눌러야 한다."""
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
        print("  댓글 게시 완료. ※ 상단 고정은 유튜브 스튜디오에서 직접 눌러주세요"
              " (API로 자동 고정은 지원되지 않습니다).")
    except Exception as e:
        print(f"  [경고] 댓글 게시 실패 (force-ssl 스코프로 재인증이 필요할 수 있습니다): {e}")


# ---------------------------------------------------------------------------
# 업로드
# ---------------------------------------------------------------------------

def upload_video(creds: Credentials, video_path: str, metadata: dict) -> str:
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": "24",  # Entertainment
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


# ---------------------------------------------------------------------------
# 스레드(Threads) 포스팅 - 유튜브 업로드 성공 후에만 호출됨, 실패해도 무시
# ---------------------------------------------------------------------------

def build_threads_text(script: dict) -> str:
    """script.json의 narration(팟캐스트 낭독 원문)을 그대로 옮긴다. 재작성 없음,
    영상 링크 없음. 500자 넘으면 뒤를 잘라서 맞춘다."""
    text = script.get("narration", "")
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


# ---------------------------------------------------------------------------
# 실패 알림
# ---------------------------------------------------------------------------

def notify_failure(stage: str, error: Exception) -> None:
    message = f":rotating_light: 쇼츠 자동화 파이프라인 실패 - [{stage}] {error}"
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    print(message)
    if webhook_url:
        try:
            requests.post(webhook_url, json={"text": message}, timeout=10)
        except Exception as e:
            print(f"  Slack 알림 전송도 실패했습니다: {e}")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    try:
        date = find_latest_date()
        print(f"대상 날짜: {date}")

        video_path = FINAL_VIDEO_PATH_TEMPLATE.format(date=date)
        script_path = SCRIPT_PATH_TEMPLATE.format(date=date)

        if not os.path.exists(script_path):
            raise FileNotFoundError(f"{script_path} 가 없습니다. fetch_script.py를 먼저 실행하세요.")

        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        print("[1/7] YouTube 인증 중...")
        creds = get_credentials()

        print("[2/7] 채널 확인 중...")
        verify_channel(creds)

        print("[3/7] 메타데이터(제목/설명/태그) 생성 중...")
        metadata = build_metadata(script)
        print(f"  제목: {metadata['title']}")

        print("[4/7] 업로드 중...")
        video_id = upload_video(creds, video_path, metadata)

        print("[5/7] 썸네일 생성 및 설정 중...")
        thumbnail_path = THUMBNAIL_PATH_TEMPLATE.format(date=date)
        build_thumbnail(script.get("title", metadata["title"]), thumbnail_path)
        set_thumbnail(creds, video_id, thumbnail_path)

        print("[6/7] 홍보용 댓글 게시 중...")
        post_pinned_style_comment(creds, video_id, PINNED_COMMENT_TEMPLATE)

        print("[7/7] 스레드 포스팅 중...")
        threads_text = build_threads_text(script)
        post_to_threads(threads_text)

        print(f"완료: https://youtube.com/shorts/{video_id}")

    except Exception as e:
        notify_failure(stage="upload_video", error=e)
        raise


if __name__ == "__main__":
    main()
