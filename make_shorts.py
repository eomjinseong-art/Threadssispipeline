"""구글 시트 YouTube 대기 사연 1개 → EP.67 디자인 Shorts → YouTube 업로드.

waitmybabe Shorts는 EP.67(wxTOaqAf51M) 디자인만 쓴다(sayeon_render.py).
대기 행에 맞는 손글씨 스펙(sayeon_specs/*.json)이 없으면 아무것도 올리지 않고 대기로 남긴다.

Threads `Status`와 무관하다. `YouTube` 열이 대기인 가장 작은 EP를 고른다.
업로드가 성공한 뒤에만 YouTube=`완료`. 업로드 실패는 YouTube=`대기`로 남겨 재시도한다.
렌더 길이가 45~58초 밖이면 그 행만 YouTube=`보류`로 표시하고 다음 대기 행으로 넘어간다.
이 파이프라인은 Threads에 글을 올리지 않는다.
"""

from __future__ import annotations

import argparse

from fetch_script import find_pending_row, load_worksheet, mark_youtube_complete, mark_youtube_hold
from sayeon_render import DurationOutOfRange, find_spec_for_title, metadata_from_spec, render_spec
from upload_video import already_posted_short_today, notify_failure, upload_spec_short

# 한 회차에서 길이 문제로 보류할 수 있는 행 수. 그 다음은 렌더를 멈추고 실패로 끝낸다.
MAX_LENGTH_HOLDS = 5


def _take_pending_spec(ws):
    """대기 1건과 그 스펙. 스펙이 없으면 (row_index, None, None, None). 대기가 없으면 (None, None, None, None)."""
    row_index, row = find_pending_row(ws)
    if row_index is None:
        return None, None, None, None
    title = str(row.get("제목", ""))
    print(f"대상 행 {row_index}: {title}")
    path, spec = find_spec_for_title(title)
    if spec is None:
        msg = (
            f"행 {row_index} '{title}' 의 EP.67 디자인 스펙(sayeon_specs/*.json)이 없어 "
            "업로드하지 않았습니다. 스펙을 추가하면 다음 회차에 올라갑니다."
        )
        print(msg)
        notify_failure(stage="spec_missing", error=RuntimeError(msg))
        return row_index, None, None, None
    print(f"스펙: {path}")
    return row_index, path, spec, title


def _render_from_queue(ws, *, hold_bad: bool):
    """길이 범위 안의 첫 대기 스펙을 렌더한다.

    hold_bad 이면 범위 밖 행은 YouTube=보류로 표시하고 다음 대기로 넘어간다.
    반환: (row_index, spec, video_path, total) 또는 업로드할 편이 없으면 None.
    스펙이 없는 첫 행을 만나면 그 행을 대기인 채로 두고 None (호출부가 0을 반환).
    """
    seen: set[int] = set()
    held = 0
    while True:
        row_index, _path, spec, title = _take_pending_spec(ws)
        if row_index is None:
            if held:
                print("길이 범위 안의 대기 사연이 없습니다. 보류로 뺀 행의 스펙을 다듬어 주세요.")
                return "exhausted"
            print("YouTube 대기 에피소드가 없습니다. 이번 회차는 건너뜁니다.")
            return None
        if spec is None:
            return None
        if row_index in seen:
            print(f"행 {row_index} 가 보류 후에도 대기로 남아 있어 이번 회차를 멈춥니다.")
            return "exhausted"
        seen.add(row_index)
        print("[render] EP.67 디자인 렌더")
        try:
            video_path, total = render_spec(spec)
        except DurationOutOfRange as exc:
            if not hold_bad:
                raise
            held += 1
            print(
                f"행 {row_index} '{title}' 를 YouTube=보류로 표시하고 다음 대기 행으로 넘어갑니다. {exc}"
            )
            notify_failure(
                stage="make_shorts",
                error=RuntimeError(
                    f"{exc} 행 {row_index} 는 YouTube=보류로 표시하고 다음 대기 행으로 넘어갑니다."
                ),
            )
            mark_youtube_hold(ws, row_index)
            if held >= MAX_LENGTH_HOLDS:
                print(f"길이 범위 밖 스펙이 {held}편 연속이라 이번 회차를 멈춥니다.")
                return "exhausted"
            continue
        print(f"  {video_path} ({total:.1f}s)")
        return row_index, spec, video_path, total


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
        print("[render] EP.67 디자인 렌더")
        video_path, total = render_spec(spec)
        print(f"  {video_path} ({total:.1f}s)")
    else:
        ws = load_worksheet()
        # 시트에 쓰는 건 실제 업로드 회차만. dry-run 은 길이 오류를 그대로 보여 준다.
        picked = _render_from_queue(ws, hold_bad=not (dry_run or skip_upload))
        if picked is None:
            return 0
        if picked == "exhausted":
            return 1
        row_index, spec, video_path, total = picked

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
