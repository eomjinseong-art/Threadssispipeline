"""
1일 1쇼츠 자동화 파이프라인 - 1단계: 구글 시트에서 사연 가져오기 (미니멀 3슬라이드 버전)

슬라이드 구성:
  1) 사연 - 상황 설명 전체
  2) 언니들 반응 - 현실언니/공감언니/폭주언니 대사 한 화면에 같이
  3) 질문 - 마무리 질문

각 슬라이드는 화면에 보일 텍스트(display_text)와, 그 슬라이드에서 실제로
낭독될 텍스트(narration_text)를 따로 가진다.

이 단계는 시트를 '완료'로 바꾸지 않는다. 완료 표시는 YouTube 업로드가
성공한 뒤에만 make_shorts.py 가 수행한다. 중간에 실패하면 Status는
'대기'로 남아 다음 실행이 같은 사연을 재시도한다.

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


def load_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise SystemExit("GOOGLE_SHEETS_CREDENTIALS 환경변수가 필요합니다.")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def load_worksheet() -> gspread.Worksheet:
    return load_client().open_by_key(SHEET_ID).sheet1


def find_pending_row(ws: gspread.Worksheet):
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Status", "")).strip() == PENDING_STATUS:
            return i, row
    return None, None


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
    """대기 행 1개를 스크립트 JSON으로 저장한다. 시트 Status는 바꾸지 않는다.

    Returns:
        (row_index, script, script_path) 또는 대기 행이 없으면 (None, None, None)
    """
    owns_ws = ws is None
    worksheet = ws if ws is not None else load_worksheet()
    row_index, row = find_pending_row(worksheet)
    if row_index is None:
        return None, None, None
    script = build_script(row, row_index)
    path = write_script(script, row_index)
    if owns_ws:
        pass
    return row_index, script, path


def mark_row_complete(ws: gspread.Worksheet, row_index: int) -> None:
    ws.update_cell(row_index, 1, COMPLETE_STATUS)
    ws.format(
        f"A{row_index}",
        {"backgroundColor": {"red": 0.71, "green": 0.84, "blue": 0.66}},
    )


def main() -> None:
    row_index, script, out_path = fetch_pending_script()
    if row_index is None:
        print("처리할 대기 상태 에피소드가 없습니다. 시트를 채워주세요.")
        sys.exit(0)

    print(f"완료: {out_path}")
    print(f"{script['title']} - 슬라이드 {len(script['slides'])}장")
    print("시트 Status는 아직 '대기'입니다. YouTube 업로드 성공 후에만 완료로 바꿉니다.")


if __name__ == "__main__":
    main()
