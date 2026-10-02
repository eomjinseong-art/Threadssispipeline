"""구글 시트 YouTube 대기 사연 1개 → EP.67 디자인 Shorts → YouTube 업로드.

waitmybabe Shorts는 EP.67(wxTOaqAf51M) 디자인만 쓴다(sayeon_render.py).
대기 행에 맞는 손글씨 스펙(sayeon_specs/*.json)이 없으면 아무것도 올리지 않고 대기로 남긴다.

Threads `Status`와 무관하다. `YouTube` 열이 대기인 가장 작은 EP를 고른다.
업로드가 성공한 뒤에만 YouTube=`완료`. 실패하면 YouTube=`대기`로 남겨 재시도한다.
이 파이프라인은 Threads에 글을 올리지 않는다.
"""

from __future__ import annotations

import argparse

from fetch_script import find_pending_row, load_worksheet, mark_youtube_complete
from sayeon_render import find_spec_for_title, metadata_from_spec, render_spec
from upload_video import already_posted_short_today, notify_failure, upload_spec_short


def run(
    *,
    dry_run: bool = False,
    script_path: str | None = None,
    skip_upload: bool = False,
) -> int:
    ws = None
    row_index = None

    if not dry_run and not script_path and already_posted_short_today():
        print("오늘(KST) 이미 Shorts를 올렸습니다. 하루 1편(19:00 KST)이라 이번 회차는 건너뜁니다.")
        return 0

    if script_path:
        import json

        with open(script_path, encoding="utf-8") as f:
            spec = json.load(f)
        print(f"로컬 EP.67 스펙 사용: {script_path}")
    else:
        ws = load_worksheet()
        row_index, row = find_pending_row(ws)
        if row_index is None:
            print("YouTube 대기 에피소드가 없습니다. 이번 회차는 건너뜁니다.")
            return 0
        title = str(row.get("제목", ""))
        print(f"대상 행 {row_index}: {title}")
        script_path, spec = find_spec_for_title(title)
        if spec is None:
            msg = (
                f"행 {row_index} '{title}' 의 EP.67 디자인 스펙(sayeon_specs/*.json)이 없어 "
                "업로드하지 않았습니다. 스펙을 추가하면 다음 회차에 올라갑니다."
            )
            print(msg)
            notify_failure(stage="spec_missing", error=RuntimeError(msg))
            return 0
        print(f"스펙: {script_path}")

    print("[render] EP.67 디자인 렌더")
    video_path, total = render_spec(spec)
    print(f"  {video_path} ({total:.1f}s)")

    if dry_run or skip_upload:
        print(f"dry-run/skip-upload: 업로드·YouTube 완료 표시를 생략합니다. 영상: {video_path}")
        return 0

    print("[youtube] Shorts 업로드")
    video_id = upload_spec_short(video_path, metadata_from_spec(spec), spec)

    if ws is not None and isinstance(row_index, int):
        mark_youtube_complete(ws, row_index)
        print(f"시트 행 {row_index} YouTube 열을 완료로 표시했습니다. Status(Threads)는 변경하지 않았습니다.")
    else:
        print("시트에 연결되지 않은 로컬 스펙이라 완료 표시를 건너뜁니다.")

    print(f"파이프라인 완료: https://youtube.com/shorts/{video_id}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube 대기 사연 1개를 Shorts로 올려 waitmybabe에 올립니다.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="영상까지 만들고 업로드/YouTube 완료 표시는 하지 않습니다.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="--dry-run 과 동일 (렌더만).",
    )
    parser.add_argument(
        "--script",
        default=None,
        help="sayeon_specs/*.json 스펙 하나로 렌더 (시트 조회 생략).",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(
            run(dry_run=args.dry_run, script_path=args.script, skip_upload=args.skip_upload)
        )
    except SystemExit:
        raise
    except Exception as exc:
        notify_failure(stage="make_shorts", error=exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
