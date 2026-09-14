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

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

BATCH_SIZE = 50
MIN_PENDING = 10
PENDING_STATUS = "대기"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """당신은 한국어 쓰레드(Threads)용 "사연" 콘텐츠 작가입니다.
여성들이 직장·연애·가족에게 사연을 올리는 톤을 씁니다.

각 사연은 반드시 이 필드를 포함합니다:
- title: 사연 제목 (10자 내외, 자극적)
- story_lines: 상황을 서술하는 문장 6~8줄 (배열), 1인칭 시점, 각 문장은
  한 줄짜리 캡션에 어울리게 짧고 명확하게. 도입(상황)→전개→갈등/감정
  흐름이 보이게 작성
- real: 리얼언니 댓글 1줄 - 팩트체크스럽고 직설적인 반응
- empathy: 공감언니 댓글 1줄 - 감정을 알아주는 반응
- rage: 분노언니 댓글 1줄 - 화나고 직설적인 반응/응원
- question: 독자용 질문 1줄 - "여러분이라면 ~하시겠어요?" 형식

소재는 직장/연애/친구/가족/시댁 인간관계에서 흔히 겪는 갈등, 배신 느낌,
경계 침해, 부당한 요구 등을 다룹니다. 자살, 미성년 성적 착취, 과도한
혐오 표현 등 위험한 소재는 쓰지 않습니다.

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


def should_generate(records: list[dict]) -> tuple[bool, list[str], int, int]:
    pending = count_pending(records)
    ep_numbers = [n for n in (ep_to_int(r.get("EP", "")) for r in records) if n is not None]
    max_ep_num = max(ep_numbers, default=0)
    next_ep_num = max_ep_num + 1
    titles = [str(r.get("제목", "")).strip() for r in records if str(r.get("제목", "")).strip()]

    if pending >= MIN_PENDING:
        return False, titles, next_ep_num, pending

    return True, titles, next_ep_num, pending


CHUNK_SIZE = 10


def generate_chunk(client: OpenAI, existing_titles: list[str], count: int) -> list[dict]:
    used_titles_text = "\n".join(f"- {t}" for t in existing_titles) or "(없음)"
    user_prompt = (
        f"아래는 이미 쓴 제목 목록입니다. 겹치지 않는 완전히 새로운 사연을 "
        f"{count}개만 만들어주세요.\n\n{used_titles_text}\n\n"
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


def stories_to_rows(stories: list[dict], start_ep_num: int) -> list[list[str]]:
    rows = []
    for i, s in enumerate(stories):
        ep_label = f"{start_ep_num + i:03d}"
        story_text = "\n".join(s["story_lines"])
        rows.append([
            PENDING_STATUS,
            ep_label,
            s["title"],
            story_text,
            s["real"],
            s["empathy"],
            s["rage"],
            s["question"],
        ])
    return rows


def main():
    gc = load_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1

    records = ws.get_all_records()
    trigger, existing_titles, next_ep_num, pending = should_generate(records)

    if not trigger:
        print(
            f"재고 충분(대기 {pending}개 ≥ {MIN_PENDING}) - 건너뜀. "
            f"다음 EP 후보: {next_ep_num:03d}"
        )
        return

    print(
        f"대기 사연 {pending}개 < {MIN_PENDING}. "
        f"EP.{next_ep_num:03d}부터 {BATCH_SIZE}개 생성 시작... (OpenAI)"
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY 환경변수가 필요합니다.")
    client = OpenAI(api_key=api_key)

    stories = generate_stories(client, existing_titles, BATCH_SIZE)

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
