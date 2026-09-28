"""
1일 1쇼츠 자동화 파이프라인 - 1단계: 구글 시트에서 사연 가져오기

숏폼은 여성 1인칭 반전 사연이다.
  1) 훅 - 처음 1~2초, 갈등 한 줄 (인트로 카드, 여기 슬라이드에는 없음)
  2) 사연 - 불공평한 상황과 사이다 반전. 3언니 대사는 읽지 않는다.
  3) 질문 - 댓글을 부르는 마무리

시트 행이 3언니 문체여도 거절하지 않는다. 사연 본문만 쓰고, 알려진 각색안이
있으면 반전과 새 제목·질문을 생성 시에만 붙인다. 현실언니/공감언니/폭주언니는
Threads(`publish_threads.py`)용으로 시트에 남겨 둔다.

YouTube 큐는 Threads `Status`와 별도이다. 제목이 같은 나중 행은 건너뛴다.
새 원작 제목(W01–W21)을 기존 백로그보다 먼저 고르고, 그다음은 각색 대상 EP다.
업로드 성공 뒤에만 YouTube 열을 완료로 바꾼다.

필요 환경변수:
  GOOGLE_SHEETS_CREDENTIALS
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import gspread
from google.oauth2.service_account import Credentials

from shorts_style import output_dir, script_path_for_row
from story_format import (
    DEFAULT_QUESTION,
    choose_hook,
    ensure_curiosity,
    ep_to_int,
    finish_sentence,
    normalize_title,
)
from topic_catalog import adaptation_index, catalog_title_keys

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

REQUIRED_COLUMNS = ["Status", "EP", "제목", "사연", "현실언니", "공감언니", "폭주언니", "질문"]
SHORTS_REQUIRED = ["EP", "제목", "사연"]
PENDING_STATUS = "대기"
COMPLETE_STATUS = "완료"
YOUTUBE_COLUMN = "YouTube"
# Studio 기준 2026-09-14: waitmybabe 에 EP.1–EP.42 업로드됨. 백필은 43부터.
YOUTUBE_SEEDED_COMPLETE_THROUGH_EP = 42


def load_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise SystemExit("GOOGLE_SHEETS_CREDENTIALS 환경변수가 필요합니다.")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def load_worksheet() -> gspread.Worksheet:
    return load_client().open_by_key(SHEET_ID).sheet1


def effective_youtube_status(row: dict) -> str:
    """명시된 YouTube 열 값, 없으면 EP 시드 규칙."""
    explicit = str(row.get(YOUTUBE_COLUMN, "")).strip()
    if explicit:
        return explicit
    ep = ep_to_int(row.get("EP", ""))
    if ep is None:
        return ""
    if ep <= YOUTUBE_SEEDED_COMPLETE_THROUGH_EP:
        return COMPLETE_STATUS
    return PENDING_STATUS


def seed_youtube_updates(records: list[dict]) -> list[tuple[int, str]]:
    """빈 YouTube 칸에 쓸 (행번호, 값). 이미 값이 있으면 건드리지 않는다."""
    updates: list[tuple[int, str]] = []
    for i, row in enumerate(records, start=2):
        if str(row.get(YOUTUBE_COLUMN, "")).strip():
            continue
        ep = ep_to_int(row.get("EP", ""))
        if ep is None:
            continue
        value = COMPLETE_STATUS if ep <= YOUTUBE_SEEDED_COMPLETE_THROUGH_EP else PENDING_STATUS
        updates.append((i, value))
    return updates


def find_adaptation(row: dict) -> dict | None:
    """알려진 10편이면 생성 시에만 쓸 반전 각색을 돌려준다."""
    by_ep, by_title = adaptation_index()
    ep = ep_to_int(row.get("EP", ""))
    if ep is not None and ep in by_ep:
        return by_ep[ep]
    key = normalize_title(str(row.get("제목", "")))
    if key and key in by_title:
        return by_title[key]
    return None


def queue_priority(row: dict) -> int:
    """0=새 원작, 1=반전 각색 대상, 2=나머지 백로그."""
    key = normalize_title(str(row.get("제목", "")))
    if key and key in catalog_title_keys():
        return 0
    if find_adaptation(row):
        return 1
    return 2


def pick_youtube_pending_row(records: list[dict]) -> tuple[int | None, dict | None]:
    """YouTube=대기 1건.

    같은 제목은 EP가 빠른 행만 남긴다(시트의 중복 제목은 건너뜀).
    새 원작 제목을 먼저, 그다음 각색 대상, 그다음 가장 작은 EP.
    Threads Status는 무시한다.
    """
    indexed: list[tuple[int, int, dict]] = []
    for i, row in enumerate(records, start=2):
        ep = ep_to_int(row.get("EP", ""))
        if ep is None:
            continue
        indexed.append((ep, i, row))
    indexed.sort(key=lambda item: (item[0], item[1]))

    seen_titles: set[str] = set()
    candidates: list[tuple[int, int, int, dict]] = []
    for ep, i, row in indexed:
        key = normalize_title(str(row.get("제목", "")))
        if key and key in seen_titles:
            continue
        if key:
            seen_titles.add(key)
        if effective_youtube_status(row) != PENDING_STATUS:
            continue
        candidates.append((queue_priority(row), ep, i, row))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _priority, _ep, idx, row = candidates[0]
    return idx, row


def youtube_column_index(headers: list[str]) -> int | None:
    try:
        return headers.index(YOUTUBE_COLUMN) + 1
    except ValueError:
        return None


def ensure_youtube_column(ws: gspread.Worksheet) -> int:
    """YouTube 열이 없으면 만들고, 빈 칸을 EP 규칙으로 시드한다. Status는 만지지 않는다."""
    headers = ws.row_values(1)
    col = youtube_column_index(headers)
    if col is None:
        col = len(headers) + 1
        ws.update_cell(1, col, YOUTUBE_COLUMN)
        print(f"시트에 '{YOUTUBE_COLUMN}' 열을 추가했습니다 (열 {col}).")

    records = ws.get_all_records()
    updates = seed_youtube_updates(records)
    if updates:
        payload = [
            {"range": gspread.utils.rowcol_to_a1(row_i, col), "values": [[value]]}
            for row_i, value in updates
        ]
        ws.batch_update(payload, value_input_option="USER_ENTERED")
        print(
            f"YouTube 열 시드 {len(updates)}칸 "
            f"(EP<={YOUTUBE_SEEDED_COMPLETE_THROUGH_EP} 완료, 이후 대기)"
        )
    return col


def find_pending_row(ws: gspread.Worksheet):
    """YouTube 대기 1건. 새 원작·각색 대상을 일반 백로그보다 먼저 고른다."""
    ensure_youtube_column(ws)
    return pick_youtube_pending_row(ws.get_all_records())


def validate_row(row: dict, ep_label: str) -> None:
    """숏폼에 필요한 열만 본다. 3언니 열이 비어도 거절하지 않는다."""
    missing = [c for c in SHORTS_REQUIRED if c not in row or str(row[c]).strip() == ""]
    if missing:
        raise SystemExit(f"EP.{ep_label} 행에 빈 컬럼이 있습니다: {missing}")


def story_lines_of(row: dict) -> list[str]:
    return [line.strip() for line in str(row.get("사연", "")).split("\n") if line.strip()]


def apply_adaptation(
    story_lines: list[str], question: str, adaptation: dict
) -> tuple[str, str, list[str], str]:
    """시트 원문에 반전 한 단락과 새 제목·질문을 붙인다. 언니 대사는 쓰지 않는다."""
    lines = list(story_lines)
    twist = str(adaptation.get("twist", "")).strip()
    blob = " ".join(lines)
    if twist and twist not in blob:
        lines.extend(finish_sentence(part) for part in twist.split("\n") if part.strip())
    title = ensure_curiosity(str(adaptation.get("title", "")))
    hook = choose_hook(title, lines, adaptation.get("hook"))
    adapted_question = str(adaptation.get("question", "")).strip() or question
    return title, hook, lines, adapted_question


def build_slides(row: dict) -> list[dict]:
    story_lines = story_lines_of(row)
    if not story_lines:
        raise SystemExit("사연 컬럼이 비어 있습니다.")

    question = str(row.get("질문", "")).strip() or DEFAULT_QUESTION
    adaptation = find_adaptation(row)
    if adaptation:
        _title, _hook, story_lines, question = apply_adaptation(story_lines, question, adaptation)
    story_lines = [finish_sentence(line) for line in story_lines]
    slides = [
        {
            "type": "story",
            "display_text": "\n".join(story_lines),
            "narration_text": " ".join(story_lines),
        },
        {
            "type": "question",
            "display_text": question,
            "narration_text": question,
        },
    ]
    for i, slide in enumerate(slides):
        slide["index"] = i
    return slides


def build_narration(slides: list[dict]) -> str:
    """전체 낭독 텍스트(업로드 설명/스레드 글감으로 재사용)."""
    return " ".join(s["narration_text"] for s in slides)


def build_script(row: dict, row_index: int, today: str | None = None) -> dict:
    ep = str(row["EP"]).strip()
    validate_row(row, ep)
    title_raw = str(row["제목"]).strip()
    lines = story_lines_of(row)
    question = str(row.get("질문", "")).strip() or DEFAULT_QUESTION
    adaptation = find_adaptation(row)
    if adaptation:
        title, hook, lines, question = apply_adaptation(lines, question, adaptation)
    else:
        title = ensure_curiosity(title_raw)
        hook = choose_hook(title, lines)
    slides = build_slides(row)
    narration = build_narration(slides)
    return {
        "date": today or dt.date.today().isoformat(),
        "row_index": row_index,
        "ep": ep,
        "title": title,
        "title_raw": title_raw,
        "hook": hook,
        "format": "twist",
        "narration": narration,
        "slides": slides,
    }


def write_script(script: dict, row_index: int | None = None) -> str:
    idx = row_index if row_index is not None else script.get("row_index")
    if idx is None:
        raise ValueError("row_index 가 필요합니다. 날짜 glob 대신 행 기반 경로를 씁니다.")
    output_dir()
    out_path = script_path_for_row(idx)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    return out_path


def fetch_pending_script(ws: gspread.Worksheet | None = None) -> tuple[int | None, dict | None, str | None]:
    """YouTube 대기 행 1개를 스크립트 JSON으로 저장한다. Status/YouTube 열은 바꾸지 않는다."""
    worksheet = ws if ws is not None else load_worksheet()
    row_index, row = find_pending_row(worksheet)
    if row_index is None:
        return None, None, None
    script = build_script(row, row_index)
    path = write_script(script, row_index)
    return row_index, script, path


def mark_youtube_complete(ws: gspread.Worksheet, row_index: int) -> None:
    """YouTube 열만 완료로 표시한다. Threads Status는 건드리지 않는다."""
    col = ensure_youtube_column(ws)
    ws.update_cell(row_index, col, COMPLETE_STATUS)
    col_a1 = gspread.utils.rowcol_to_a1(row_index, col)
    ws.format(
        col_a1,
        {"backgroundColor": {"red": 0.71, "green": 0.84, "blue": 0.66}},
    )


def main() -> None:
    row_index, script, out_path = fetch_pending_script()
    if row_index is None:
        print("YouTube 대기 에피소드가 없습니다. 시트를 채워주세요.")
        sys.exit(0)

    print(f"완료: {out_path}")
    print(f"{script['title']} - 슬라이드 {len(script['slides'])}장")
    print("YouTube 열은 아직 '대기'입니다. 업로드 성공 후에만 완료로 바꿉니다. Status(Threads)는 그대로입니다.")


if __name__ == "__main__":
    main()
