# 언니들 사연 → YouTube Shorts 자동화

구글 시트에서 `Status=대기`인 사연 1개를 가져와 **세로(9:16) Shorts 영상**을 만들고 YouTube에 올립니다. 업로드가 **성공한 뒤에만** 해당 행을 `완료`로 바꿉니다. 그 전에 실패하면 `대기`로 남겨 다음 스케줄이 같은 사연을 다시 시도합니다.

시각 언어는 기존 3슬라이드(사연 / 언니들 반응 / 질문) + 타이핑 자막 + 검은 인트로 타이틀 카드입니다.

## 스케줄

GitHub Actions `daily-shorts-pipeline` (`.github/workflows/daily_shorts.yml`):

| 한국시간(KST) | UTC |
| --- | --- |
| 오전 9시 | 00:00 |
| 오후 6시 | 09:00 |
| 오후 9시 | 12:00 |

수동 실행: Actions → **daily-shorts-pipeline** → Run workflow.

각 실행마다:

1. (조건부) 대기 사연이 적으면 OpenAI로 시트에 새 사연을 채움 (`generate_more_stories.py`, `OPENAI_API_KEY`)
2. `Status=대기` 다음 행 1개로 3슬라이드 대본 작성
3. edge-tts 나레이션 + 단어 단위 타이핑 자막
4. 1080×1920 / 25fps / h264+aac 영상 조립 (인트로 카드 + BGM)
5. YouTube Data API v3로 Shorts 업로드 (전체 모드, dry-run 아님)
6. 성공 시에만 시트 `완료`
7. (선택) Threads 홍보 글. **실패해도 런은 성공**이고 시트도 되돌리지 않음
8. 렌더된 mp4는 Actions artifact로 보관

## Threads 스케줄은 수동만

같은 시트 `대기` 행을 Shorts와 Threads가 동시에 가져가지 않도록, `daily_threads.yml` 은 **스케줄을 제거하고 `workflow_dispatch`만** 남겼습니다. 텍스트만 Threads에 올리고 싶을 때 Actions에서 직접 실행하세요.

## 필요한 GitHub Actions 시크릿

Settings → Secrets and variables → Actions

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `GOOGLE_SHEETS_CREDENTIALS` | 필수 | 시트 서비스 계정 JSON |
| `YOUTUBE_TOKEN_JSON` | 필수 | `reauth_youtube.py`가 만든 `token.json` 전체 |
| `YOUTUBE_CLIENT_SECRET_JSON` | 권장 | OAuth 클라이언트 JSON 전체. 토큰 갱신에 사용 |
| `YOUTUBE_REFRESH_TOKEN` | 권장 | `token.json`의 refresh_token 백업 |
| `EXPECTED_YOUTUBE_CHANNEL_ID` | 권장 | 이 ID와 다르면 **업로드를 중단**. 아직 없으면 경고만 하고 진행 |
| `OPENAI_API_KEY` | 선택 | 사연 재고 자동 보충 |
| `THREADS_ACCESS_TOKEN` | 선택 | 업로드 후 Threads 홍보 |
| `THREADS_USER_ID` | 선택 | Threads 사용자 ID |
| `SLACK_WEBHOOK_URL` | 선택 | 실패 알림 |

채널 ID 검증을 켜 두세요. 예전에 인증 화면에서 다른 브랜드 계정(**그날의남녀**, **Feedscanai**)을 고르면 영상이 그 채널에 조용히 올라간 적이 있습니다. ID가 다르면 크게 실패하는 편이 안전합니다.

## YouTube 재인증 (로컬 1회)

```bash
python -m pip install -r requirements.txt
# Google Cloud Console에서 YouTube Data API v3 + OAuth 데스크톱 클라이언트
# client_secret.json 을 이 폴더에 둔 뒤:
python reauth_youtube.py
```

브라우저에서 **이 쇼츠를 올릴 채널**로만 로그인하세요. 출력되는 채널 이름/ID를 확인한 다음:

- `token.json` 내용 → `YOUTUBE_TOKEN_JSON`
- `refresh_token` → `YOUTUBE_REFRESH_TOKEN`
- `client_secret.json` 내용 → `YOUTUBE_CLIENT_SECRET_JSON`
- 채널 ID → `EXPECTED_YOUTUBE_CHANNEL_ID`

`token.json` / `client_secret.json` / `output/` 은 커밋하지 않습니다.

헤드리스 Actions는 `YOUTUBE_TOKEN_JSON`을 `token.json`으로 쓰고, 만료되면 refresh token으로 갱신합니다. 브라우저 로그인은 CI에서 열지 않습니다.

## 로컬에서 돌리기

의존성: Python 3.11+, ffmpeg, 한글 폰트(Ubuntu: `fonts-nanum`, 또는 저장소의 `assets/subtitle.ttf`).

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests

# 시트 없이 샘플 대본만 렌더 (업로드/완료 표시 없음)
python make_shorts.py --script tests/fixtures/script_ep40.json --dry-run

# 대기 사연 1개 실제 업로드
GOOGLE_SHEETS_CREDENTIALS='...' python make_shorts.py
```

단계만 따로 실행할 때는 경로를 명시하세요. **날짜 glob으로 최신 파일을 고르지 않습니다.**

```bash
python fetch_script.py                          # output/script_row{N}.json (시트는 아직 대기)
python generate_media.py --script output/script_row12.json
python assemble_video.py --manifest output/manifest_row12.json --script output/script_row12.json
python upload_video.py --video output/final_row12.mp4 --script output/script_row12.json
```

`fetch_script.py`만 실행해도 시트를 `완료`로 바꾸지 않습니다.

## 영상 스펙

- 1080×1920, 25fps, H.264 + AAC 44.1kHz 스테레오, 60초 미만
- 인트로 ~2.2초: 검은 배경 + 흰 한글 제목
- 본문: 종이색 배경 RGB(246,246,244) + 슬라이드 라벨 + 타이핑 자막
- `assets/bgm.mp3`: 직접 만든 짧은 패드 루프(저작권 음원 아님). 나레이션이 나올 때 덕킹. 파일이 없으면 믹스를 건너뛰고 크래시하지 않음

## 시트 컬럼

`Status`, `EP`, `제목`, `사연`, `현실언니`, `공감언니`, `폭주언니`, `질문`

시트 ID는 `fetch_script.py`에 있습니다.

## 대시보드

`dashboard.html`을 브라우저에서 열면 시크릿 존재 여부를 확인하고 `daily-shorts-pipeline`을 수동 실행할 수 있습니다.
