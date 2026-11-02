# 커밋된 콘텐츠 큐

스케줄 워크플로(`.github/workflows/daily_threads.yml`, `daily_shorts.yml`)는 LLM을 호출하지 않습니다. 사람이 사연과 Shorts 스펙을 미리 써서 이 저장소에 커밋하고, Actions는 그 큐만 시트로 옮긴 뒤 기존 게시 단계(`publish_threads.py`, `make_shorts.py`)를 그대로 실행합니다.

큐가 비어 있으면 보충 단계는 실패하지 않고 다음 로그만 남기고 끝납니다.

```
[content-queue] 큐가 비어 있어 이번 보충을 건너뜁니다.
```

## 파일

| 경로 | 역할 |
| --- | --- |
| `content_queue/queue.json` | 아직 시트에 넘기지 않을 사연. 각 항목이 Threads 글과 Shorts 스펙 경로를 가집니다. |
| `content_queue/state.json` | 이미 소비한 항목 id. `consumed_ids` 배열. |
| `sayeon_specs/sayeon_epNNN.json` | Shorts 렌더 스펙. `topic`이 시트 `제목`과 맞아야 `make_shorts.py`가 찾습니다. `reference/`는 예시이며 큐에 넣지 않습니다. |

시트 행이 있어야 게시가 됩니다. 큐 파일만 있고 시트에 없으면 그 회차에는 올라가지 않고, 반대로 스펙 파일만 있고 큐 항목이 없으면 새 행을 만들지 않습니다.

## 항목 스키마

`queue.json`:

```json
{
  "version": 1,
  "items": [ { "...항목..." } ]
}
```

항목 필드:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | string | 고유 id. 스펙 회차와 맞추면 `ep069`처럼 세 자리입니다. |
| `title` | string | 시트 `제목`. 스펙 `topic`과 같아야 합니다. |
| `story_lines` | string[] | 시트 `사연`. 한 줄이 한 문장. |
| `real` | string | Threads `현실언니`. |
| `empathy` | string | Threads `공감언니`. |
| `rage` | string | Threads `폭주언니`. |
| `question` | string | 시트 `질문`. |
| `spec` | string | 저장소 상대 경로. 예: `sayeon_specs/sayeon_ep069.json`. |

전체 예시 (`ep069`):

```json
{
  "id": "ep069",
  "title": "내 명품백 빌려 가서 중고로 판 시누이, 결말은?",
  "story_lines": [
    "시누이한테 빌려준 가방이, 중고 앱에 올라와 있었어요.",
    "결혼 삼 주년 선물로 받은 가방이었어요. 시누이가 친구 결혼식에 하루만 들고 가겠다더라고요.",
    "그런데 일주일 뒤, 중고 앱에 똑같은 가방이 떴어요. 손잡이 긁힌 자국까지 그대로였죠.",
    "그래서 저는, 영수증 한 장으로 답하기로 했어요.",
    "십 분 뒤, 중고 앱의 판매 글이 사라졌어요.",
    "주말에 시누이가 같은 가방을 새로 사서 들고 왔어요. 그 뒤로 빌려 달라는 말은 없답니다."
  ],
  "real": "증거가 남으면 그 다음 말이 짧아져요.",
  "empathy": "그 말, 집에 와서도 남았을 거예요.",
  "rage": "가족이라는 말로 넘길 일은 아니었어요.",
  "question": "여러분이라면 단톡에 올리셨을까요?",
  "spec": "sayeon_specs/sayeon_ep069.json"
}
```

`state.json`:

```json
{
  "consumed_ids": []
}
```

## 소비와 상태

`consume_content_queue.py`가 스케줄에서 돌아갑니다. Threads 워크플로는 `--channel threads`, Shorts 워크플로는 `--channel shorts`입니다. 둘 다 같은 큐를 보고, 한 행이 Threads `Status`와 YouTube 열을 같이 채웁니다.

1. `consumed_ids`에 없는 항목만 후보입니다.
2. 시트에 같은 제목(EP 접두, `#Shorts`, 끝의 `, 결말은?` 차이는 무시)이 이미 있으면 다시 붙이지 않고 그 id만 `consumed_ids`에 넣습니다.
3. Threads 대기와 YouTube 대기가 둘 다 10개 이상이면 더 이상 옮기지 않습니다. 로그: `[content-queue] 재고가 충분해 큐를 소비하지 않고 건너뜁니다.`
4. 그렇지 않으면 스펙 파일이 있는 항목을, 두 대기 수가 10이 되거나 큐가 빌 때까지 시트 끝에 추가합니다. 새 행은 `Status=대기`이고 YouTube 칸은 비워 두어 다음 Shorts 실행이 시드합니다.
5. 추가한 id를 `consumed_ids`에 기록합니다.
6. GitHub Actions에서는 `content_queue/state.json`만 커밋하고 기본 브랜치로 푸시합니다. 푸시가 실패해도 작업은 실패하지 않습니다. 다음 실행이 시트 제목으로 다시 맞춰 같은 사연을 두 번 넣지 않습니다.

스펙이 없는 제목은 넣지 않습니다. `make_shorts.py`는 스펙이 없는 첫 대기 행에서 업로드를 멈추기 때문입니다.

남은 수를 보려면:

```bash
python consume_content_queue.py --report
```

시트에 쓰지 않고 어떤 항목이 나갈지만 보려면 `python consume_content_queue.py --dry-run`.

## 남은 일수

게시 주기:

- Threads: 하루 3회. cron `30 0,9,12 * * *` (한국시간 09:30, 18:30, 21:30).
- Shorts: 하루 1회. cron `0 10 * * *` (한국시간 19:00).

```
남은 항목 = consumed_ids 에 없고, story_lines 와 spec 파일이 있는 항목 수
Threads 일수 = 남은 항목 / 3
Shorts 일수  = 남은 항목 / 1
```

이 수는 저장소 큐만 셉니다. 시트에 이미 `대기`인 행은 포함하지 않습니다. id가 `consumed_ids`에 들어가면, 아직 게시 전이라도 시트에 넘어간 것으로 보고 이 수에서 빠집니다.

지금 커밋 기준 (`consumed_ids`가 비어 있음):

Threads 남은 항목: 13 (4.33일) / Shorts 남은 항목: 13 (13.00일)

시트에 같은 제목이 이미 있으면 다음 Actions 실행이 그 항목을 소비로만 표시합니다. 그 뒤의 일수는 `python consume_content_queue.py --report`로 다시 계산합니다.

## 항목을 더할 때

1. `sayeon_specs/sayeon_epNNN.json`을 추가합니다. `topic`은 큐 `title`과 같게 합니다.
2. `content_queue/queue.json`의 `items` 끝에 위 스키마대로 항목을 넣습니다. 새 id는 `consumed_ids`에 넣지 않습니다.
3. 커밋합니다. 스케줄이 대기 재고가 10개 미만일 때 시트로 옮깁니다.

## 수동 LLM

`generate_more_stories.py`와 `refill_queue.py`는 사람이 직접 돌릴 때만 LLM을 씁니다. `GEMINI_API_KEY`가 있으면 Gemini OpenAI 호환 엔드포인트(`https://generativelanguage.googleapis.com/v1beta/openai/`)의 `gemini-2.5-flash`를 쓰고, 없을 때만 `OPENAI_API_KEY`로 폴백합니다. 스케줄 워크플로는 두 스크립트를 실행하지 않습니다. Actions 안에서 실수로 실행돼도 모델을 호출하지 않고 같은 안내 로그만 남깁니다.
