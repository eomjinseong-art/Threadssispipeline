"""
1일 1쇼츠 자동화 파이프라인 - 1단계: 구글 시트에서 사연 가져오기 (미니멀 3슬라이드 버전)

슬라이드 구성:
  1) 사연 - 상황 설명 전체
  2) 언니들 반응 - 현실언니/공감언니/폭주언니 대사 한 화면에 같이
  3) 질문 - 마무리 질문

각 슬라이드는 화면에 보일 텍스트(display_text)와, 그 슬라이드에서 실제로
낭독될 텍스트(narration_text)를 따로 가진다.

YouTube 큐는 Threads `Status`와 별도이다. `YouTube` 열(`대기`/`완료`)을
보고 EP가 가장 작은 대기 행을 고른다. 열이 없으면 만들고, EP<=42는
이미 채널에 올라간 것으로 `완료`, EP>=43은 `대기`로 시드한다.
이 단계는 Threads `Status`를 바꾸지 않는다. YouTube 열 완료 표시는
업로드 성공 뒤에만 make_shorts.py 가 수행한다.

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

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

INTRO = "안녕하세요, 오늘도 사연 하나 들고 왔습니다."

REQUIRED_COLUMNS = ["Status", "EP", "제목", "사연", "현실언니", "공감언니", "폭주언니", "질문"]
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


def ep_to_int(raw) -> int | None:
    s = str(raw).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


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


def pick_youtube_pending_row(records: list[dict]) -> tuple[int | None, dict | None]:
    """YouTube=대기 중 EP가 가장 작은 행. Threads Status는 무시한다."""
    candidates: list[tuple[int, int, dict]] = []
    for i, row in enumerate(records, start=2):
        if effective_youtube_status(row) != PENDING_STATUS:
            continue
        ep = ep_to_int(row.get("EP", ""))
        if ep is None:
            continue
        candidates.append((ep, i, row))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _ep, idx, row = candidates[0]
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
    """YouTube 대기 중 가장 작은 EP. Threads Status=완료 행도 대상이 된다."""
    ensure_youtube_column(ws)
    return pick_youtube_pending_row(ws.get_all_records())


def validate_row(row: dict, ep_label: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in row or str(row[c]).strip() == ""]
    if missing:
        raise SystemExit(f"EP.{ep_label} 행에 빈 컬럼이 있습니다: {missing}")


def build_slides(row: dict) -> list[dict]:
    story_lines = [s.strip() for s in str(row["사연"]).split("\n") if s.strip()]
    if not story_lines:
        raise SystemExit("사연 컬럼이 비어 있습니다.")

    real = str(row["현실언니"]).strip()
    empathy = str(row["공감언니"]).strip()
    rage = str(row["폭주언니"]).strip()
    question = str(row["질문"]).strip()

    slides = [
        {
            "type": "story",
            "display_text": "\n".join(story_lines),
            "narration_text": f"{INTRO} " + " ".join(story_lines),
        },
        {
            "type": "reactions",
            "display_text": (
                f"현실언니: {real}\n\n공감언니: {empathy}\n\n폭주언니: {rage}"
            ),
            "narration_text": (
                f"현실언니는 이렇게 말합니다. {real} "
                f"공감언니는 이렇게 말합니다. {empathy} "
                f"그리고 폭주언니는 이렇게 말합니다. {rage}"
            ),
        },
        {
            "type": "question",
            "display_text": question,
            "narration_text": question,
        },
    ]

    for i, s in enumerate(slides):
        s["index"] = i

    return slides


def build_narration(slides: list[dict]) -> str:
    """전체 낭독 텍스트(업로드 설명/스레드 글감으로 재사용)."""
    return " ".join(s["narration_text"] for s in slides)


def build_script(row: dict, row_index: int, today: str | None = None) -> dict:
    ep = str(row["EP"]).strip()
    validate_row(row, ep)
    title_raw = str(row["제목"]).strip()
    slides = build_slides(row)
    narration = build_narration(slides)
    return {
        "date": today or dt.date.today().isoformat(),
        "row_index": row_index,
        "ep": ep,
        "title": f"EP.{ep} {title_raw}",
        "title_raw": title_raw,
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
