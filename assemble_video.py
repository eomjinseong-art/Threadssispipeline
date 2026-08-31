"""
1일 1쇼츠 자동화 파이프라인 - 3단계: 영상 조립 (타이핑 자막 버전)

generate_media.py가 만든 output/manifest_{date}.json(슬라이드별 배경이미지+
음성+타이핑자막.ass+길이)을 받아서, 슬라이드마다 배경 위에 자막을 실시간으로
그려 넣은 세그먼트 3개를 만들고 순서대로 이어붙여 최종 세로형(9:16) mp4를
만든다.

필요 프로그램: ffmpeg, ffprobe

출력:
  output/final_{date}.mp4
"""

import os
import json
import subprocess
import datetime as dt
import tempfile

MANIFEST_PATH_TEMPLATE = "output/manifest_{date}.json"
SEGMENTS_DIR_TEMPLATE = "output/segments_{date}"
FINAL_PATH_TEMPLATE = "output/final_{date}.mp4"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"명령 실행 실패: {' '.join(cmd)}\n--- stderr ---\n{result.stderr}")


def get_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {result.stderr}")
    return float(result.stdout.strip())


def escape_ass_path_for_filter(path: str) -> str:
    """ffmpeg -vf ass=... 필터에 경로를 넣을 때 콜론/역슬래시를 이스케이프."""
    p = os.path.abspath(path).replace("\\", "/").replace(":", "\\:")
    return p


def build_segment(image_path: str, audio_path: str, ass_path: str, out_path: str) -> None:
    duration = get_duration(audio_path)
    ass_escaped = escape_ass_path_for_filter(ass_path)
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass='{ass_escaped}'"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ])


def concat_segments(segment_paths: list[str], out_path: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tf:
        for p in segment_paths:
            tf.write(f"file '{os.path.abspath(p)}'\n")
        list_file = tf.name
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_path])
    os.unlink(list_file)


def main():
    today = dt.date.today().isoformat()
    manifest_path = MANIFEST_PATH_TEMPLATE.format(date=today)
    if not os.path.exists(manifest_path):
        raise SystemExit(f"{manifest_path} 가 없습니다. generate_media.py를 먼저 실행하세요.")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    segments_dir = SEGMENTS_DIR_TEMPLATE.format(date=today)
    segment_paths = []

    for slide in manifest["slides"]:
        seg_path = os.path.join(segments_dir, f"{slide['index']:02d}.mp4")
        print(f"[{slide['index'] + 1}/{len(manifest['slides'])}] 세그먼트 렌더링: "
              f"{slide['type']} ({slide['duration']:.2f}초)")
        build_segment(slide["image_path"], slide["audio_path"], slide["ass_path"], seg_path)
        segment_paths.append(seg_path)

    final_path = FINAL_PATH_TEMPLATE.format(date=today)
    print("세그먼트 이어붙이는 중...")
    concat_segments(segment_paths, final_path)

    print(f"완료: {final_path} (총 {manifest['total_duration']:.1f}초)")


if __name__ == "__main__":
    main()
