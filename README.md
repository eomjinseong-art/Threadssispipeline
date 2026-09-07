# 스레드 언니들 자동 배포

유튜브 쇼츠 생성/업로드는 **중단**했습니다. 이 저장소는 구글 시트의 사연을 **Threads 글만** 하루 3번 올립니다. 영상, 나레이션, 유튜브 인증은 더 이상 사용하지 않습니다.

## 하는 일

한국시간 **오전 9시 / 오후 6시 / 오후 9시**에 GitHub Actions가:

1. (조건부) 사연 재고가 바닥나면 Claude가 시트에 새 사연을 채움
2. 시트에서 `Status = 대기`인 다음 사연 1개를 고름
3. 제목 + 사연 + 현실/공감/폭주 언니 반응 + 질문을 Threads 텍스트로 게시
4. **게시가 성공한 뒤에만** 해당 행을 `완료`로 바꿈

대기 사연이 없으면 이번 회차는 그냥 건너뜁니다. 유튜브 성공 여부와는 상관없습니다.

Threads 글은 500자 제한에 맞춰 사연을 먼저 줄입니다.

## GitHub에서 유튜브를 끄려면

이 파일들을 [Threadssispipeline](https://github.com/eomjinseong-art/Threadssispipeline) `main`에 그대로 올리면 됩니다.

- 새 워크플로: `.github/workflows/daily_threads.yml` (스레드 배포)
- 옛 워크플로: `.github/workflows/daily_shorts.yml` (스케줄 제거, 영상 작업 안 함)

올리지 않으면 GitHub 쪽 기존 `daily-shorts-pipeline`이 계속 영상을 만들려고 합니다.

## 필요한 시크릿

GitHub → Settings → Secrets and variables → Actions

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `GOOGLE_SHEETS_CREDENTIALS` | 필수 | 시트 서비스 계정 JSON |
| `THREADS_ACCESS_TOKEN` | 필수 | Threads API 액세스 토큰 |
| `THREADS_USER_ID` | 필수 | Threads 사용자 ID |
| `ANTHROPIC_API_KEY` | 선택 | 사연 재고 자동 보충 |
| `SLACK_WEBHOOK_URL` | 선택 | 실패 알림 |

유튜브 관련 시크릿(`YOUTUBE_TOKEN_JSON` 등)은 더 이상 필요 없습니다.

## 로컬에서 확인

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
GOOGLE_SHEETS_CREDENTIALS='...' python publish_threads.py --dry-run
```

`--dry-run`은 문구만 출력하고 스레드/시트를 건드리지 않습니다.

## 대시보드

`dashboard.html`을 브라우저에서 열면 시크릿 존재 여부를 확인하고, `daily-threads-pipeline`을 수동 실행할 수 있습니다.
