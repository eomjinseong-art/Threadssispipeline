"""
스레드 전용 자동 배포.

유튜브/영상 생성과 무관하게, 구글 시트에서 Status=대기인 사연 1개를 가져와
Threads에 텍스트로 게시한다. 게시가 성공한 뒤에만 해당 행을 완료로 바꾼다.

필요 환경변수:
  GOOGLE_SHEETS_CREDENTIALS  (필수)
  THREADS_ACCESS_TOKEN       (필수)
  THREADS_USER_ID            (필수)
  SLACK_WEBHOOK_URL          (선택 - 실패 알림)

사용:
  python publish_threads.py
  python publish_threads.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import gspread
import requests
from google.oauth2.service_account import Credentials

SHEET_ID = "1AOvI5ExbZ4j_BJHZvZnWnXExCDOebjxgsiRr7SWfuDE"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
REQUIRED_COLUMNS = ["Status", "EP", "제목", "사연", "현실언니", "공감언니", "폭주언니", "질문"]

THREADS_API_BASE = "https://graph.threads.net/v1.0"
THREADS_MAX_CHARS = 500


def load_sheet() -> gspread.Worksheet:
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise SystemExit("GOOGLE_SHEETS_CREDENTIALS 환경변수가 필요합니다.")
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SHEET_SCOPES)
    return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1


def find_pending_row(ws: gspread.Worksheet) -> tuple[int | None, dict | None]:
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Status", "")).strip() == "대기":
            return i, row
    return None, None


def validate_row(row: dict, ep_label: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in row or str(row[c]).strip() == ""]
    if missing:
        raise SystemExit(f"EP.{ep_label} 행에 빈 컬럼이 있습니다: {missing}")


def assemble_post(header: str, story: str, reactions: str, question: str) -> str:
    blocks = [header]
    if story:
        blocks.append(story)
    if reactions:
        blocks.append(reactions)
    if question:
        blocks.append(question)
    return "\n\n".join(blocks)


def build_threads_text(row: dict) -> str:
    ep = str(row["EP"]).strip()
    title = str(row["제목"]).strip()
    story = str(row["사연"]).strip()
    real = str(row["현실언니"]).strip()
    empathy = str(row["공감언니"]).strip()
    rage = str(row["폭주언니"]).strip()
    question = str(row["질문"]).strip()

    header = f"EP.{ep} {title}"
    reactions = f"현실언니: {real}\n공감언니: {empathy}\n폭주언니: {rage}"

    text = assemble_post(header, story, reactions, question)
    if len(text) <= THREADS_MAX_CHARS:
        return text

    story_one_line = " ".join(story.split())
    text = assemble_post(header, story_one_line, reactions, question)
    if len(text) <= THREADS_MAX_CHARS:
        return text

    overflow = len(text) - THREADS_MAX_CHARS
    keep = len(story_one_line) - overflow - 3
    if keep >= 40:
        return assemble_post(header, story_one_line[:keep].rstrip() + "...", reactions, question)

    without_story = assemble_post(header, "", reactions, question)
    if len(without_story) <= THREADS_MAX_CHARS:
        return without_story
    return without_story[: THREADS_MAX_CHARS - 3] + "..."


def post_to_threads(text: str) -> str:
    access_token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not access_token or not user_id:
        raise SystemExit("THREADS_ACCESS_TOKEN / THREADS_USER_ID 가 없습니다.")

    create_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads",
        data={"media_type": "TEXT", "text": text, "access_token": access_token},
        timeout=30,
    )
    create_data = create_resp.json()
    if "id" not in create_data:
        raise RuntimeError(f"스레드 컨테이너 생성 실패: {create_data}")

    publish_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        data={"creation_id": create_data["id"], "access_token": access_token},
        timeout=30,
    )
    publish_data = publish_resp.json()
    if "id" not in publish_data:
        raise RuntimeError(f"스레드 퍼블리시 실패: {publish_data}")

    return str(publish_data["id"])


def mark_complete(ws: gspread.Worksheet, row_index: int) -> None:
    ws.update_cell(row_index, 1, "완료")
    ws.format(
        f"A{row_index}",
        {"backgroundColor": {"red": 0.71, "green": 0.84, "blue": 0.66}},
    )


def notify_failure(error: Exception) -> None:
    message = f":rotating_light: 스레드 자동 배포 실패 - {error}"
    print(message)
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"text": message}, timeout=10)
    except Exception as slack_error:
        print(f"  Slack 알림 전송도 실패했습니다: {slack_error}")


def run(dry_run: bool = False) -> int:
    ws = load_sheet()
    row_index, row = find_pending_row(ws)
    if row is None:
        print("처리할 대기 상태 에피소드가 없습니다. 이번 회차는 건너뜁니다.")
        return 0

    ep = str(row["EP"]).strip()
    validate_row(row, ep)
    text = build_threads_text(row)
    print(f"대상: EP.{ep} {str(row['제목']).strip()}")
    print(f"글자 수: {len(text)} / {THREADS_MAX_CHARS}")
    print("--- 게시 문구 ---")
    print(text)
    print("----------------")

    if dry_run:
        print("dry-run: 스레드에 올리지 않았고, 시트도 바꾸지 않았습니다.")
        return 0

    post_id = post_to_threads(text)
    mark_complete(ws, row_index)
    print(f"스레드 게시 완료 (게시물 ID: {post_id}). 시트 EP.{ep} 를 완료로 표시했습니다.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="구글 시트 사연을 Threads에 게시합니다.")
    parser.add_argument("--dry-run", action="store_true", help="게시/시트 변경 없이 문구만 출력")
    args = parser.parse_args()
    try:
        raise SystemExit(run(dry_run=args.dry_run))
    except SystemExit:
        raise
    except Exception as e:
        notify_failure(e)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
