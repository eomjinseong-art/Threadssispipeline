"""Copy pre-written stories from the committed queue onto the Google Sheet.

Scheduled workflows run this instead of ``generate_more_stories.py``.
It never calls an LLM. An empty queue logs a skip line and exits 0.

  python consume_content_queue.py --channel threads
  python consume_content_queue.py --channel shorts
  python consume_content_queue.py --report
  python consume_content_queue.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from content_queue import (
    QUEUE_PATH,
    STATE_PATH,
    commit_state_if_actions,
    format_inventory,
    inventory,
    load_queue,
    load_state,
    run_consume,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="커밋된 사연 큐를 시트로 보충합니다. LLM은 호출하지 않습니다.")
    parser.add_argument("--channel", choices=("threads", "shorts", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true", help="시트와 상태 파일을 바꾸지 않습니다.")
    parser.add_argument("--report", action="store_true", help="남은 항목과 일수만 출력합니다.")
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    args = parser.parse_args(argv)

    if args.report:
        try:
            items = load_queue(args.queue) if args.queue.exists() else []
            state = load_state(args.state)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"[content-queue] 큐를 읽지 못했습니다: {exc}")
            return 1
        print("[content-queue] " + format_inventory(inventory(items, state)))
        return 0

    code = run_consume(
        queue_path=args.queue,
        state_path=args.state,
        dry_run=args.dry_run,
        channel=args.channel,
    )
    if code == 0 and not args.dry_run:
        commit_state_if_actions(args.state)
    return code


if __name__ == "__main__":
    sys.exit(main())
