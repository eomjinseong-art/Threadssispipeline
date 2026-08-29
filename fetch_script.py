"""
1일 1쇼츠 자동화 파이프라인 - 1단계: 구글 시트에서 사연 가져오기 (미니멀 3슬라이드 버전)

[재설계 배경] 기존 방식(턴마다 개별 TTS+세그먼트, 최대 11개)은 장애 지점이
많아서(음성 API, 채널 인증, 시트 형식 등 어디서든 깨지면 전체가 안 됨)
계속 문제가 반복됐다. 그래서 슬라이드를 3장으로 줄이고, 유료 ElevenLabs
대신 무료 edge-tts로 바꿔서 비용도 없애고 장애 지점도 최소화했다.

슬라이드 구성:
  1) 사연 - 상황 설명 전체
  2) 언니들 반응 - 현실언니/공감언니/폭주언니 대사 한 화면에 같이
  3) 질문 - 마무리 질문

각 슬라이드는 화면에 보일 텍스트(display_text)와, 그 슬라이드에서 실제로
낭독될 텍스트(narration_text, 팟캐스트 진행자가 "현실언니는 이렇게 말합니다"
식으로 화자를 소개하며 읽는 문장)를 따로 가진다.

필요 환경변수:
  GOOGLE_SHEETS_CREDENTIALS

필요 패키지:
  pip install gspread google-auth --break-system-packages
"""

import os
import json
import sys
import datetime as dt

import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SCRIPT_PATH_TEMPLATE = "output/script_{date}.json"

INTRO = "안녕하세요, 오늘도 사연 하나 들고 왔습니다."

REQUIRED_COLUMNS = ["Status", "EP", "제목", "사연", "현실언니", "공감언니", "폭주언니", "질문"]


def load_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise SystemExit("GOOGLE_SHEETS_CREDENTIALS 환경변수가 필요합니다.")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def find_pending_row(ws: gspread.Worksheet):
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Status", "")).strip() == "대기":
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


def main():
    gc = load_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1

    row_index, row = find_pending_row(ws)
    if row is None:
        print("처리할 대기 상태 에피소드가 없습니다. 시트를 채워주세요.")
        sys.exit(1)

    ep = str(row["EP"]).strip()
    validate_row(row, ep)

    title_raw = str(row["제목"]).strip()
    slides = build_slides(row)
    narration = build_narration(slides)

    today = dt.date.today().isoformat()
    output = {
        "date": today,
        "ep": ep,
        "title": f"EP.{ep} {title_raw}",
        "narration": narration,
        "slides": slides,
    }

    os.makedirs("output", exist_ok=True)
    out_path = SCRIPT_PATH_TEMPLATE.format(date=today)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    ws.update_cell(row_index, 1, "완료")
    ws.format(f"A{row_index}", {"backgroundColor": {"red": 0.71, "green": 0.84, "blue": 0.66}})

    print(f"완료: {out_path}")
    print(f"EP.{ep} {title_raw} - 슬라이드 {len(slides)}장")


if __name__ == "__main__":
    main()
