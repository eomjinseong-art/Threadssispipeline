"""새 반전 사연을 구글 시트 끝에 추가한다.

기존 행은 지우거나 덮어쓰지 않는다. 제목이 이미 있으면 건너뛴다.
adapted_10 의 원본 EP가 시트에 있으면 그 행은 Shorts 생성 때 각색하므로
같은 사연을 한 번 더 넣지 않는다.

필요 환경변수:
  GOOGLE_SHEETS_CREDENTIALS

사용:
  python append_sheet_topics.py --dry-run
  python append_sheet_topics.py
"""

from __future__ import annotations

import argparse
import os

from fetch_script import ep_to_int, load_worksheet
from story_format import normalize_title
from topic_catalog import load_adaptations, topics_to_append

PENDING = "대기"


def sheet_snapshot(records: list[dict]) -> tuple[set[str], set[int], int]:
    titles = {normalize_title(row.get("제목", "")) for row in records}
    titles.discard("")
    eps = {ep for ep in (ep_to_int(row.get("EP", "")) for row in records) if ep is not None}
    next_ep = max(eps, default=0) + 1
    return titles, eps, next_ep


def values_for_headers(headers: list[str], topic: dict) -> list[str]:
    story = topic.get("story_lines") or []
    if isinstance(story, str):
        story_text = story
    else:
        story_text = "\n".join(story)
    mapping = {
        "Status": PENDING,
        "EP": str(topic.get("ep", "")),
        "제목": topic.get("title", ""),
        "사연": story_text,
        "현실언니": topic.get("real", ""),
        "공감언니": topic.get("empathy", ""),
        "폭주언니": topic.get("rage", ""),
        "질문": topic.get("question", ""),
        "YouTube": PENDING,
    }
    return [mapping.get(header, "") for header in headers]


def overlay_eps(existing_eps: set[int]) -> list[int]:
    return sorted(item["ep"] for item in load_adaptations() if item["ep"] in existing_eps)


def print_plan(topics: list[dict], overlays: list[int]) -> None:
    print(f"추가 예정 {len(topics)}행")
    for topic in topics:
        print(f"  EP.{topic['ep']} {topic['title']}")
    if overlays:
        joined = ", ".join(str(ep) for ep in overlays)
        print(
            "각색만 적용(행 추가 안 함) EP "
            f"{joined}. 시트 원문은 유지하고 Shorts를 만들 때 반전을 붙입니다."
        )


def run(dry_run: bool = False) -> int:
    if dry_run and not os.environ.get("GOOGLE_SHEETS_CREDENTIALS"):
        topics = topics_to_append(set(), set(), 1)
        print("자격 증명 없음: 빈 시트 기준으로 미리보기만 합니다.")
        print_plan(topics, [])
        print("dry-run: 시트에 쓰지 않았습니다.")
        return 0

    ws = load_worksheet()
    records = ws.get_all_records()
    titles, eps, next_ep = sheet_snapshot(records)
    topics = topics_to_append(titles, eps, next_ep)
    overlays = overlay_eps(eps)
    print_plan(topics, overlays)
    if dry_run:
        print("dry-run: 시트에 쓰지 않았습니다.")
        return 0
    if not topics:
        print("추가할 새 제목이 없습니다.")
        return 0
    headers = ws.row_values(1)
    if "제목" not in headers or "사연" not in headers:
        raise SystemExit(f"시트 헤더를 해석할 수 없습니다: {headers}")
    values = [values_for_headers(headers, topic) for topic in topics]
    ws.append_rows(values, value_input_option="USER_ENTERED")
    print(f"시트 끝에 {len(values)}행을 추가했습니다. 기존 행은 변경하지 않았습니다.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="반전 사연을 시트 끝에 추가합니다.")
    parser.add_argument("--dry-run", action="store_true", help="시트에 쓰지 않고 추가 목록만 출력")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
