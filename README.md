# 언니들 사연 → YouTube Shorts 자동화

구글 시트에서 **YouTube 열이 `대기`인 사연 1개**를 여성 1인칭 반전 숏폼으로 만들어 [waitmybabe](https://www.youtube.com/@waitmybabe) 채널에 올립니다. 3언니 반응 열은 Threads용으로만 남기고 Shorts 내레이션에는 넣지 않습니다.

Threads `Status`와는 완전히 별개입니다. 이 파이프라인은 Threads에 글을 올리지 않고, `Status` 칸도 바꾸지 않습니다.

## 디자인: EP.67 전용 (2026-10-02~)

waitmybabe Shorts는 **EP.67 '내가 차린 제사상, 시어머니 공으로?'(https://youtube.com/shorts/wxTOaqAf51M) 디자인만** 씁니다.
웜 베이지 + `오늘의 사연 · EP.N` 라벨, 명조체 훅 카드, 흰 스토리 카드(로즈 라인), 단톡방 말풍선·사진 카드, 강조 카드, 공감 질문 + 창작 표기. 45~58초.

- 렌더러: `sayeon_engine/` (`sayeon_render.py`가 호출). 폰트: Noto CJK·Noto Color Emoji(apt), Gowun Batang(`assets/fonts/`).
- 대기 행마다 **손으로 쓴 스펙** `sayeon_specs/sayeon_epNNN.json`이 필요합니다. `topic`에 시트 `제목`을 그대로 적습니다(", 결말은?" 유무는 무시하고 매칭).
- 스펙이 없으면 **렌더·업로드하지 않고** 행을 `대기`로 남기며 Slack으로 알립니다. 예전(타이핑 자막/흰 배경) 디자인으로 대신 올리는 경로는 없습니다.
- 기준 스펙: `sayeon_specs/reference/sayeon_ep067.json`, `sayeon_ep068.json`.
- 로컬 확인: `python sayeon_render.py sayeon_specs/sayeon_ep073.json` 또는 `python make_shorts.py --dry-run --script <spec>`.

## 시트 열: `Status` vs `YouTube`

| 열 | 누가 쓰나 | 값 |
| --- | --- | --- |
| `Status` | Threads 전용 (`publish_threads.py`) | `대기` / `완료` |
| `YouTube` | Shorts 전용 (`make_shorts.py`) | `대기` / `완료` |

`YouTube` 열이 없으면 첫 실행이 만듭니다.

시드 (2026-09-14 Studio 기준, waitmybabe에 EP.1–EP.42가 이미 있음):

- EP ≤ 42, 칸이 비어 있으면 → `완료`
- EP ≥ 43, 칸이 비어 있으면 → `대기` → **백필은 EP.43 `내 결혼을 반대하는 절친`부터**

이미 값이 있는 칸은 덮어쓰지 않습니다. 업로드가 **성공한 뒤에만** `YouTube=완료`. 실패하면 `대기`로 남아 다음 스케줄이 같은 EP를 재시도합니다.

채널 ID: `UCbMITZoZxPQrmKsZdbwUB7g` (`EXPECTED_YOUTUBE_CHANNEL_ID`). 불일치면 업로드를 중단합니다.

## 스케줄

GitHub Actions `daily-shorts-pipeline` (`.github/workflows/daily_shorts.yml`):

| 한국시간(KST) | UTC |
| --- | --- |
| 오후 7시 | 10:00 |

하루 1편. 같은 한국 날짜에 채널 업로드가 이미 있으면 렌더·업로드·시트 완료 표시를 하지 않습니다. 수동 실행이 스케줄과 겹쳐도 `shorts-publish` 그룹에서 한 번에 하나만 진행합니다. 수동: Actions → **daily-shorts-pipeline** → Run workflow.

각 실행:

1. (조건부) 사연 재고 보충 (`generate_more_stories.py`, `OPENAI_API_KEY`) — 새 행의 `Status`는 대기. YouTube 칸은 다음 Shorts 실행이 시드
2. `YouTube=대기` 중 가장 작은 EP 1개
3. edge-tts + 2~3줄 타이핑 자막 (문장/화자 바뀌면 창을 비움)
4. 1080×1920 / 25fps 조립 (인트로 + 들릴 정도의 BGM)
5. YouTube Shorts 업로드
6. 성공 시에만 `YouTube=완료`
7. mp4 artifact 보관

## Threads 자동 배포

`daily-threads-pipeline` (`.github/workflows/daily_threads.yml`)는 Shorts와 별도로 `Status=대기` 행 하나를 Threads에 올립니다. 게시가 성공한 뒤에만 `Status=완료`로 바꿉니다. Shorts는 `YouTube` 열만 읽고 쓰며 `Status`는 바꾸지 않으므로 두 큐가 겹치지 않습니다. Threads 글에는 현실언니/공감언니/폭주언니 줄을 그대로 넣습니다. Shorts 워크플로는 Threads 토큰을 쓰지 않습니다.

| 한국시간(KST) | UTC |
| --- | --- |
| 오전 9시 30분 | 00:30 |
| 오후 6시 30분 | 09:30 |
| 오후 9시 30분 | 12:30 |

cron: `30 0,9,12 * * *`. 같은 그룹의 실행이 겹치면 `threads-publish`에서 기다립니다 (`cancel-in-progress: false`). 수동 실행: Actions → **daily-threads-pipeline** → Run workflow. 실패 Slack 문구는 스케줄 실행이면 `자동`, `workflow_dispatch`이면 `수동`입니다.

장기 액세스 토큰은 약 60일입니다. `refresh-threads-token` (`.github/workflows/refresh_threads_token.yml`)이 매주 월요일 03:17 UTC (`17 3 * * 1`, 한국시간 12:17)에 갱신합니다. 수동 실행도 됩니다.

```
GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=...
```

새 토큰은 로그에 남기지 않고 `THREADS_ACCESS_TOKEN` 시크릿에 다시 씁니다. 이 저장에는 **이 저장소의 Secrets 읽기/쓰기 권한이 있는 fine-grained PAT**가 필요하며, 그 PAT를 Actions 시크릿 `SECRETS_WRITE_TOKEN`으로 넣어야 합니다. 시크릿이 없으면 워크플로는 갱신 API 결과를 확인한 뒤 경고만 출력하고 토큰은 저장하지 않습니다. 작업이 실패로 끝나는 것은 갱신 API 호출 자체가 실패할 때뿐입니다.

## 필요한 GitHub Actions 시크릿

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `GOOGLE_SHEETS_CREDENTIALS` | 필수 | 시트 서비스 계정 JSON |
| `YOUTUBE_TOKEN_JSON` | 필수 | `reauth_youtube.py`가 만든 `token.json` 전체 |
| `YOUTUBE_CLIENT_SECRET_JSON` | 권장 | OAuth 클라이언트 JSON (trailing 텍스트 있어도 첫 객체만 사용) |
| `YOUTUBE_REFRESH_TOKEN` | 권장 | refresh token 백업 |
| `EXPECTED_YOUTUBE_CHANNEL_ID` | 권장 | `UCbMITZoZxPQrmKsZdbwUB7g` (waitmybabe). 다르면 업로드 중단 |
| `OPENAI_API_KEY` | 선택 | 사연 재고 보충 |
| `SLACK_WEBHOOK_URL` | 선택 | 실패 알림 |
| `THREADS_ACCESS_TOKEN` | Threads 필수 | long-lived 토큰. 주간 갱신 워크플로가 교체 |
| `THREADS_USER_ID` | Threads 필수 | Threads 사용자 ID |
| `SECRETS_WRITE_TOKEN` | 토큰 갱신에 필요 | 이 저장소 Secrets 읽기/쓰기 권한이 있는 fine-grained PAT |

과거 다른 브랜드 계정(그날의남녀, Feedscanai)에 올라간 사고가 있어 채널 ID 검증을 켭니다.

## YouTube 재인증 (로컬 1회)

```bash
python -m pip install -r requirements.txt
python reauth_youtube.py
```

브라우저에서 **waitmybabe** 로만 로그인하세요. 출력 ID가 `UCbMITZoZxPQrmKsZdbwUB7g` 인지 확인한 뒤 시크릿에 넣습니다. `token.json` / `client_secret.json` / `output/` 은 커밋하지 않습니다.

## 로컬에서 돌리기

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests

# 시트/업로드 없이 QA 렌더
python make_shorts.py --script tests/fixtures/script_ep102.json --dry-run

# 시트에 붙일 새 사연 목록만 확인
python append_sheet_topics.py --dry-run
```

업로드는 QA를 통과한 뒤에만 하세요.

```bash
python fetch_script.py
python generate_media.py --script output/script_row43.json
python assemble_video.py --manifest output/manifest_row43.json --script output/script_row43.json
python upload_video.py --video output/final_row43.mp4 --script output/script_row43.json
```

## 영상 스펙

- 1080×1920, 25fps, H.264 + AAC 44.1kHz 스테레오, 60초 미만
- 처음 1.8초: 소프트 베이지 배경 + 갈등 한 줄(훅). 검은 카드는 쓰지 않습니다.
- 본문: 여성 목소리(`ko-KR-SunHiNeural`)로 1인칭 사연과 사이다 반전을 읽고, 마지막에 댓글 질문을 읽습니다. 3언니 대사는 읽지 않습니다.
- 자막은 Shorts 안전 영역 안(위 검색창, 오른쪽 버튼, 아래 제목/설명 밖)에 2~3줄만
- 제목은 갈등으로 시작하고 `EP.`로 시작하지 않습니다. 채널 이름은 끝에 `| waitmybabe`로 붙일 수 있습니다.
- 시트 행이 예전 3언니 문체여도 사연 본문으로 만들고, `topics/adapted_10.csv`에 있는 EP는 생성 때 반전을 붙입니다.
- `assets/bgm.mp3`: 직접 만든 12초 펜타토닉 플럭+패드 루프. TTS 아래에도 바닥에 남김

## 새 사연 추가

`python append_sheet_topics.py` 가 `topics/w01_w21.csv`를 시트 **끝**에 추가합니다. 기존 행은 지우거나 덮어쓰지 않고, 같은 제목은 건너뜁니다. `adapted_10.csv`의 원본 EP가 이미 있으면 행을 더 넣지 않고 Shorts를 만들 때 각색합니다. 자격 증명 없이 목록만 보려면 `python append_sheet_topics.py --dry-run`.

YouTube 대기 또는 Threads 대기가 10개 미만이면 `generate_more_stories.py`가 같은 반전 형식으로 50개를 보충합니다. Threads용 3언니 줄도 같이 채웁니다. 고를 때는 새 원작 제목을 먼저, 그다음 각색 대상 EP, 그다음 가장 작은 EP를 쓰고 중복 제목은 건너뜁니다.

## 시트 컬럼

`Status`, `EP`, `제목`, `사연`, `현실언니`, `공감언니`, `폭주언니`, `질문`, `YouTube`

시트 ID는 `fetch_script.py`에 있습니다.
