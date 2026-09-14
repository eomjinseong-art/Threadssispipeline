"""구글 시트 대기 사연 1개 → 세로 Shorts 영상 → YouTube 업로드 오케스트레이터.

실패 시 시트 Status는 '대기'로 남겨 다음 스케줄이 같은 사연을 재시도한다.
YouTube 업로드가 성공한 뒤에만 행을 '완료'로 바꾼다.
스레드 홍보는 업로드 성공 후 최선을 다해 시도하며, 실패해도 런을 실패 처리하지 않고
시트를 되돌리지도 않는다.
"""

from __future__ import annotations

import argparse

from assemble_video import assemble_from_manifest
from fetch_script import fetch_pending_script, load_worksheet, mark_row_complete
from generate_media import generate_media
from upload_video import (
    build_threads_text,
    notify_failure,
    post_to_threads,
    upload_short,
)


def run(
    *,
    dry_run: bool = False,
    script_path: str | None = None,
    skip_upload: bool = False,
) -> int:
    ws = None
    row_index = None
    script = None

    if script_path:
        import json

        with open(script_path, encoding="utf-8") as f:
            script = json.load(f)
        row_index = script.get("row_index", "local")
        print(f"로컬 스크립트 사용: {script_path} (row {row_index})")
    else:
        ws = load_worksheet()
        row_index, script, script_path = fetch_pending_script(ws)
        if row_index is None:
            print("처리할 대기 상태 에피소드가 없습니다. 이번 회차는 건너뜁니다.")
            return 0
        print(f"대상 행 {row_index}: {script['title']}")

    print("[media] TTS + 타이핑 자막 생성")
    manifest_path = generate_media(script_path)

    print("[assemble] 9:16 Shorts 조립")
    video_path = assemble_from_manifest(manifest_path, script_path=script_path)

    if dry_run or skip_upload:
        print(f"dry-run/skip-upload: 업로드·시트 완료 표시를 생략합니다. 영상: {video_path}")
        return 0

    print("[youtube] Shorts 업로드")
    video_id = upload_short(video_path, script_path)

    if ws is not None and isinstance(row_index, int):
        mark_row_complete(ws, row_index)
        print(f"시트 행 {row_index} 을 완료로 표시했습니다.")
    else:
        print("시트에 연결되지 않은 로컬 스크립트라 완료 표시를 건너뜁니다.")

    print("[threads] 홍보 글 (실패해도 무시)")
    try:
        post_to_threads(build_threads_text(script, video_id=video_id))
    except Exception as exc:
        print(f"  [경고] 스레드 홍보 실패(런은 성공 유지, 시트도 완료 유지): {exc}")

    print(f"파이프라인 완료: https://youtube.com/shorts/{video_id}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="대기 사연 1개를 Shorts로 만들어 YouTube에 올립니다.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="영상까지 만들고 업로드/시트 완료 표시는 하지 않습니다.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="--dry-run 과 동일 (렌더만).",
    )
    parser.add_argument(
        "--script",
        default=None,
        help="이미 있는 script_rowN.json 으로 렌더 (시트 조회 생략).",
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
