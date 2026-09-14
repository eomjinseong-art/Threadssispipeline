"""로컬에서 1회 YouTube OAuth를 수행해 token.json 을 만들고 채널 ID를 출력한다.

GitHub Actions 시크릿:
  YOUTUBE_TOKEN_JSON          <- token.json 전체
  YOUTUBE_REFRESH_TOKEN       <- token.json 의 refresh_token (백업)
  YOUTUBE_CLIENT_SECRET_JSON  <- client_secret.json 전체
  EXPECTED_YOUTUBE_CHANNEL_ID <- 아래에 출력되는 채널 ID (잘못된 채널 업로드 방지)

과거 사고: 인증 화면에서 다른 브랜드 계정(그날의남녀, Feedscanai)을 고르면
영상이 그 채널에 조용히 올라갔다. 출력된 채널 이름/ID를 눈으로 확인한 뒤
시크릿에 등록하세요.
"""

from __future__ import annotations

import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from upload_video import CLIENT_SECRET_PATH, SCOPES, TOKEN_PATH


def main() -> None:
    if not os.path.exists(CLIENT_SECRET_PATH):
        print(
            f"{CLIENT_SECRET_PATH} 가 없습니다.\n"
            "Google Cloud Console → APIs & Services → Credentials 에서\n"
            "OAuth 클라이언트(데스크톱) JSON을 받아 이 파일 이름으로 저장하세요.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("브라우저가 열립니다. 업로드할 YouTube 채널 계정으로 로그인하세요.")
    print("브랜드 계정이 여러 개면 반드시 이 쇼츠 채널만 고르세요.")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        print("연결된 채널을 찾지 못했습니다. 토큰은 저장됐으니 채널 권한을 확인하세요.")
        print(f"저장됨: {os.path.abspath(TOKEN_PATH)}")
        return

    channel_id = items[0]["id"]
    title = items[0]["snippet"]["title"]
    token = json.loads(creds.to_json())

    print()
    print("=== 인증 성공 ===")
    print(f"채널 이름: {title}")
    print(f"채널 ID  : {channel_id}")
    print(f"token.json: {os.path.abspath(TOKEN_PATH)}")
    print()
    print("GitHub → Settings → Secrets and variables → Actions 에 등록:")
    print("  YOUTUBE_TOKEN_JSON         = token.json 파일 내용 전체")
    if token.get("refresh_token"):
        print("  YOUTUBE_REFRESH_TOKEN      = (아래 refresh_token)")
        print(f"                               {token['refresh_token']}")
    else:
        print("  [경고] refresh_token 이 없습니다. 동의 화면에서 offline access를 허용했는지 확인하세요.")
    print("  YOUTUBE_CLIENT_SECRET_JSON = client_secret.json 파일 내용 전체")
    print(f"  EXPECTED_YOUTUBE_CHANNEL_ID = {channel_id}")
    print()
    print("token.json / client_secret.json 은 커밋하지 마세요.")


if __name__ == "__main__":
    main()
