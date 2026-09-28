"""
쓰레드 언니들 사연 자동화 - 사연 재고 자동 보충

구글 시트에서 Status가 "대기"인 사연이 일정 개수 미만이면
OpenAI(ChatGPT)로 새 사연을 생성해 시트 끝에 추가한다.

필요 환경변수:
  OPENAI_API_KEY
  GOOGLE_SHEETS_CREDENTIALS
"""

import os
import json

import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

from story_format import ensure_curiosity, normalize_title, strip_leading_ep

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

BATCH_SIZE = 50
MIN_PENDING = 10
PENDING_STATUS = "대기"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """당신은 한국어 숏폼·쓰레드용 창작 사연 작가입니다.
여성 1인칭입니다. 불공평한 장면으로 시작해, 주인공이 증거·제3자·정중하지만
날카로운 한마디로 되갚는 사이다 반전으로 끝냅니다.
실제 게시글, 뉴스, 실존 인물의 사연은 베끼지 마세요. 전부 창작입니다.

각 사연은 반드시 이 필드를 포함합니다:
- title: 갈등과 호기심이 앞에 오는 제목. 예: "도어락 비번 알아낸 시어머니, 결말은?"
  EP 번호는 넣지 마세요. 앞 20자 안에 가해자와 선을 넘은 행동이 보이게.
- story_lines: 6~8줄 배열. 1인칭. 한 줄에 한 문장.
  첫 줄은 화면 첫 1~2초에 쓸 갈등 훅. 가운데는 상대의 구체적인 한마디.
  마지막 1~2줄은 사이다 반전으로 끝내세요. 3언니 대사로 끝내지 마세요.
- real: 현실언니 댓글 1줄. Threads에만 씁니다. 숏폼 내레이션에는 안 들어갑니다.
- empathy: 공감언니 댓글 1줄. Threads용.
- rage: 폭주언니 댓글 1줄. Threads용.
- question: 댓글이 갈리는 질문 1줄. "여러분이라면 ~?" 형식.

주제 비중: 10편 중 6편 이상은 시댁·시어머니·남편·가족 경계(내 공간, 내 돈,
내 공로, 내 육아)처럼 댓글이 양쪽으로 갈리는 상황. 나머지는 연인, 직장 동료,
친구의 선 넘기.
자살, 미성년 대상 성적 내용, 범죄 실행 방법, 혐오 선동은 쓰지 마세요.

반드시 JSON 배열만 출력하세요. 다른 설명이나 마크다운을 붙이지 마세요.
스키마: [{"title": str, "story_lines": [str, ...], "real": str,
"empathy": str, "rage": str, "question": str}, ...]
"""


def load_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise SystemExit("GOOGLE_SHEETS_CREDENTIALS 환경변수가 필요합니다.")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def ep_to_int(raw) -> int | None:
    s = str(raw).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def count_pending(records: list[dict]) -> int:
    return sum(
        1
        for r in records
        if str(r.get("Status", "")).strip() == PENDING_STATUS
    )


def count_youtube_pending(records: list[dict]) -> int:
    """YouTube 열 기준 대기. 칸이 비어 있으면 EP 시드 규칙을 따른다."""
    from fetch_script import effective_youtube_status

    return sum(1 for row in records if effective_youtube_status(row) == PENDING_STATUS)


def should_generate(records: list[dict]) -> tuple[bool, list[str], int, int]:
    """Threads 대기 또는 YouTube 대기가 10개 미만이면 보충한다."""
    pending = count_pending(records)
    youtube_pending = count_youtube_pending(records)
    ep_numbers = [n for n in (ep_to_int(r.get("EP", "")) for r in records) if n is not None]
    max_ep_num = max(ep_numbers, default=0)
    next_ep_num = max_ep_num + 1
    titles = [str(r.get("제목", "")).strip() for r in records if str(r.get("제목", "")).strip()]

    if pending >= MIN_PENDING and youtube_pending >= MIN_PENDING:
        return False, titles, next_ep_num, pending

    return True, titles, next_ep_num, pending


CHUNK_SIZE = 10


def generate_chunk(client: OpenAI, existing_titles: list[str], count: int) -> list[dict]:
    used_titles_text = "\n".join(f"- {t}" for t in existing_titles) or "(없음)"
    user_prompt = (
        f"아래는 이미 쓴 제목 목록입니다. 겹치지 않는 완전히 새로운 사연을 "
        f"{count}개만 만들어주세요. 제목은 EP로 시작하지 말고, 첫 줄은 갈등 훅, "
        f"마지막 줄은 사이다 반전으로 쓰세요. 댓글이 갈리는 시댁·가족 경계를 더 많이.\n\n"
        f"{used_titles_text}\n\n"
        f"JSON 배열 {count}개, 스키마 그대로 지켜주세요."
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.9,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n응답은 {\"stories\": [...]} 형태의 JSON 객체로 주세요."},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content or ""
    raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
    data = json.loads(raw)

    if isinstance(data, dict):
        if "stories" in data and isinstance(data["stories"], list):
            data = data["stories"]
        else:
            # fallback: first list value
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break
    if not isinstance(data, list):
        raise ValueError(f"예상치 못한 응답 형식(배열이 아님): {type(data)}")

    return data


def generate_stories(client: OpenAI, existing_titles: list[str], count: int) -> list[dict]:
    all_stories: list[dict] = []
    titles_pool = list(existing_titles)
    remaining = count

    while remaining > 0:
        chunk_size = min(CHUNK_SIZE, remaining)
        print(f"  생성 중... ({len(all_stories)}/{count}) model={OPENAI_MODEL}")
        chunk = generate_chunk(client, titles_pool, chunk_size)

        if not chunk:
            print("  [경고] 이번 요청에서 0개 반환, 중단합니다.")
            break

        all_stories.extend(chunk)
        titles_pool.extend(s.get("title", "") for s in chunk if s.get("title"))
        remaining -= len(chunk)

        if len(chunk) < chunk_size:
            print(f"  [경고] {chunk_size}개 요청했는데 {len(chunk)}개만 반환")

    return all_stories


def validate_story(story: dict, idx: int) -> list[str]:
    errors = []
    required = ["title", "story_lines", "real", "empathy", "rage", "question"]
    for key in required:
        if key not in story or not story[key]:
            errors.append(f"{idx}번째 항목: '{key}' 필드 없음/비어있음")
    if "story_lines" in story and isinstance(story["story_lines"], list):
        n = len(story["story_lines"])
        if not (5 <= n <= 9):
            errors.append(f"{idx}번째 항목: story_lines {n}줄 (권장 6~8줄)")
    elif "story_lines" in story:
        errors.append(f"{idx}번째 항목: story_lines가 배열이 아님")
    return errors


def drop_duplicate_stories(stories: list[dict], existing_titles: list[str]) -> list[dict]:
    """이미 있는 제목, 그리고 이번 배치 안의 중복 제목은 버린다."""
    seen = {normalize_title(title) for title in existing_titles}
    seen.discard("")
    kept: list[dict] = []
    for story in stories:
        key = normalize_title(str(story.get("title", "")))
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(story)
    return kept


def stories_to_rows(stories: list[dict], start_ep_num: int) -> list[list[str]]:
    rows = []
    for i, story in enumerate(stories):
        ep_label = f"{start_ep_num + i:03d}"
        story_text = "\n".join(story["story_lines"])
        title = ensure_curiosity(strip_leading_ep(str(story.get("title", ""))))
        rows.append([
            PENDING_STATUS,
            ep_label,
            title,
            story_text,
            story["real"],
            story["empathy"],
            story["rage"],
            story["question"],
        ])
    return rows


def main():
    gc = load_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1

    records = ws.get_all_records()
    trigger, existing_titles, next_ep_num, pending = should_generate(records)
    youtube_pending = count_youtube_pending(records)

    if not trigger:
        print(
            f"재고 충분(Threads 대기 {pending}개, YouTube 대기 {youtube_pending}개, "
            f"둘 다 ≥ {MIN_PENDING}) - 건너뜀. 다음 EP 후보: {next_ep_num:03d}"
        )
        return

    print(
        f"재고 부족(Threads 대기 {pending}개, YouTube 대기 {youtube_pending}개, "
        f"기준 {MIN_PENDING}). EP.{next_ep_num:03d}부터 {BATCH_SIZE}개 생성 시작... (OpenAI)"
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY 환경변수가 필요합니다.")
    client = OpenAI(api_key=api_key)

    stories = generate_stories(client, existing_titles, BATCH_SIZE)
    before = len(stories)
    stories = drop_duplicate_stories(stories, existing_titles)
    if len(stories) != before:
        print(f"[안내] 기존 제목과 겹치는 사연 {before - len(stories)}개를 제외했습니다.")

    all_errors = []
    for i, s in enumerate(stories, start=1):
        all_errors.extend(validate_story(s, i))
    if all_errors:
        raise SystemExit("생성된 사연 검증 실패:\n" + "\n".join(all_errors))

    if len(stories) != BATCH_SIZE:
        print(f"[경고] 요청 {BATCH_SIZE}개 중 {len(stories)}개만 생성됨. 있는 만큼만 추가합니다.")

    if not stories:
        raise SystemExit("생성된 사연이 없습니다.")

    rows = stories_to_rows(stories, next_ep_num)
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    print(
        f"완료: EP.{next_ep_num:03d}~EP.{next_ep_num + len(rows) - 1:03d} "
        f"({len(rows)}개) 시트에 추가됨"
    )


if __name__ == "__main__":
    main()
