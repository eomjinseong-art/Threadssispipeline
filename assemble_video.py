"""
1일 1쇼츠 자동화 파이프라인 - 3단계: 영상 조립 (타이핑 자막 버전)

generate_media.py가 만든 output/manifest_row{N}.json 을 받아
  1) 검은 인트로 타이틀 카드 (~2.2초, 흰 한글 제목)
  2) 슬라이드 3장 (종이 배경 + 타이핑 자막)
을 1080x1920 / 25fps / h264+aac 44.1kHz 스테레오로 이어붙인다.

BGM이 assets/ 에 있으면 나레이션 아래에 덕킹해서 섞고, 없으면 건너뛴다.
최종 길이는 60초 미만으로 맞춘다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

from shorts_style import (
    AUDIO_CHANNELS,
    AUDIO_RATE,
    INTRO_BG,
    INTRO_DURATION,
    INTRO_FG,
    MAX_DURATION_SEC,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    find_bgm_path,
    final_path_for_row,
    get_font,
    resolve_korean_font,
    wrap_korean,
)

FFMPEG_VIDEO_ARGS = [
    "-r", str(VIDEO_FPS),
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
]
FFMPEG_AUDIO_ARGS = [
    "-c:a", "aac",
    "-b:a", "128k",
    "-ar", str(AUDIO_RATE),
    "-ac", str(AUDIO_CHANNELS),
]


def run(cmd: list[str]) -> None:
    """ffmpeg/ffprobe를 UTF-8로 실행한다 (Windows cp949 decode 오류 방지)."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        joined = " ".join(cmd)
        raise RuntimeError(
            f"명령 실행 실패: {joined}\n--- stderr ---\n{result.stderr}"
        )


def get_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {result.stderr}")
    return float(result.stdout.strip())


def escape_filter_path(path: str) -> str:
    """ffmpeg 필터 그래프에 넣을 경로 이스케이프 (콜론/역슬래시/' )."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")
    return p


def escape_ass_path_for_filter(path: str) -> str:
    return escape_filter_path(path)


def fontsdir_for_ass() -> str:
    font_path, _family = resolve_korean_font()
    return os.path.dirname(os.path.abspath(font_path))


def build_intro_card(title: str, out_path: str) -> None:
    """검은 배경에 흰 한글 제목을 가운데 정렬한 인트로 카드."""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), INTRO_BG)
    draw = ImageDraw.Draw(img)
    font = get_font(72)
    max_width = VIDEO_WIDTH - 160
    lines = wrap_korean(title, font, max_width)

    line_heights: list[int] = []
    line_widths: list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
    spacing = 18
    total_h = sum(line_heights) + spacing * max(0, len(lines) - 1)
    y = (VIDEO_HEIGHT - total_h) // 2
    for line, w, h in zip(lines, line_widths, line_heights):
        x = (VIDEO_WIDTH - w) // 2
        draw.text((x, y), line, font=font, fill=INTRO_FG)
        y += h + spacing

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)


def build_intro_segment(title: str, out_path: str, duration: float = INTRO_DURATION) -> None:
    img_path = out_path.replace(".mp4", "_intro.png")
    build_intro_card(title, img_path)
    vf = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},fps={VIDEO_FPS}"
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", img_path,
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
        "-vf", vf,
        "-t", f"{duration:.3f}",
        *FFMPEG_VIDEO_ARGS,
        *FFMPEG_AUDIO_ARGS,
        "-shortest",
        out_path,
    ])


def build_segment(image_path: str, audio_path: str, ass_path: str, out_path: str) -> None:
    duration = get_duration(audio_path)
    ass_escaped = escape_ass_path_for_filter(ass_path)
    fontsdir = escape_filter_path(fontsdir_for_ass())
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},fps={VIDEO_FPS},"
        f"ass='{ass_escaped}':fontsdir='{fontsdir}'"
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-t", str(duration),
        *FFMPEG_VIDEO_ARGS,
        *FFMPEG_AUDIO_ARGS,
        "-shortest",
        out_path,
    ])


def concat_segments(segment_paths: list[str], out_path: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tf:
        for p in segment_paths:
            abs_p = os.path.abspath(p).replace("\\", "/")
            tf.write(f"file '{abs_p}'\n")
        list_file = tf.name
    try:
        run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(VIDEO_FPS),
            *FFMPEG_AUDIO_ARGS,
            out_path,
        ])
    finally:
        os.unlink(list_file)


def _atempo_chain(speed: float) -> str:
    """atempo는 0.5~2.0만 지원하므로 범위를 나눠 체인한다."""
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0 + 1e-6:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 - 1e-6:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def enforce_max_duration(video_path: str, max_sec: float = MAX_DURATION_SEC) -> str:
    duration = get_duration(video_path)
    if duration <= max_sec:
        return video_path
    factor = duration / max_sec
    print(f"  길이가 {duration:.1f}초라 {factor:.2f}배속으로 {max_sec:.1f}초 안에 맞춥니다.")
    sped = video_path.replace(".mp4", "_sped.mp4")
    vf = f"setpts=PTS/{factor:.6f},fps={VIDEO_FPS}"
    af = _atempo_chain(factor)
    run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-af", af,
        *FFMPEG_VIDEO_ARGS,
        *FFMPEG_AUDIO_ARGS,
        sped,
    ])
    os.replace(sped, video_path)
    return video_path


def mix_bgm(video_path: str, bgm_path: str | None = None) -> str:
    """나레이션 아래 조용한 BGM을 덕킹해서 섞는다. 파일이 없으면 그대로 둔다."""
    bgm = bgm_path if bgm_path is not None else find_bgm_path()
    if not bgm or not os.path.isfile(bgm):
        print("  [안내] BGM 파일이 없어 배경음악을 건너뜁니다.")
        return video_path

    duration = get_duration(video_path)
    mixed = video_path.replace(".mp4", "_bgm.mp4")
    # 나레이션이 나오는 동안 BGM을 눌러서 TTS가 묻히지 않게 한다.
    filter_complex = (
        "[0:a]aformat=sample_rates="
        f"{AUDIO_RATE}:channel_layouts=stereo,asplit=2[voice][sc];"
        "[1:a]aformat=sample_rates="
        f"{AUDIO_RATE}:channel_layouts=stereo,volume=0.11[bg];"
        "[bg][sc]sidechaincompress=threshold=0.04:ratio=8:attack=40:release=350:makeup=1:knee=8[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    try:
        run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", bgm,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[a]",
            "-t", f"{duration:.3f}",
            "-c:v", "copy",
            *FFMPEG_AUDIO_ARGS,
            mixed,
        ])
    except RuntimeError as exc:
        print(f"  [경고] sidechain 덕킹 실패, 단순 믹스로 재시도: {exc}")
        simple = (
            "[1:a]aformat=sample_rates="
            f"{AUDIO_RATE}:channel_layouts=stereo,volume=0.07[bg];"
            "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )
        run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", bgm,
            "-filter_complex", simple,
            "-map", "0:v", "-map", "[a]",
            "-t", f"{duration:.3f}",
            "-c:v", "copy",
            *FFMPEG_AUDIO_ARGS,
            mixed,
        ])
    os.replace(mixed, video_path)
    print(f"  BGM 믹스 완료: {os.path.basename(bgm)}")
    return video_path


def assemble_from_manifest(
    manifest_path: str,
    script_path: str | None = None,
    out_path: str | None = None,
) -> str:
    """명시된 manifest(+선택 script)로 최종 mp4를 만들고 경로를 반환한다."""
    if not os.path.exists(manifest_path):
        raise SystemExit(f"{manifest_path} 가 없습니다. generate_media.py를 먼저 실행하세요.")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    title = manifest.get("title") or "언니들의 사연"
    row_index = manifest.get("row_index")
    if script_path:
        with open(script_path, encoding="utf-8") as f:
            script = json.load(f)
        title = script.get("title", title)
        row_index = script.get("row_index", row_index)

    if row_index is None:
        raise SystemExit("manifest/script 에 row_index가 없습니다. 행 기반 경로를 사용하세요.")

    if out_path is None:
        out_path = final_path_for_row(row_index)

    work_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), f"segments_row{row_index}")
    os.makedirs(work_dir, exist_ok=True)

    intro_path = os.path.join(work_dir, "intro.mp4")
    print(f"[intro] 타이틀 카드 {INTRO_DURATION:.1f}초: {title}")
    build_intro_segment(title, intro_path)

    segment_paths = [intro_path]
    for slide in manifest["slides"]:
        seg_path = os.path.join(work_dir, f"{slide['index']:02d}.mp4")
        print(
            f"[{slide['index'] + 1}/{len(manifest['slides'])}] 세그먼트 렌더링: "
            f"{slide['type']} ({slide['duration']:.2f}초)"
        )
        build_segment(slide["image_path"], slide["audio_path"], slide["ass_path"], seg_path)
        segment_paths.append(seg_path)

    print("세그먼트 이어붙이는 중...")
    concat_segments(segment_paths, out_path)
    mix_bgm(out_path)
    enforce_max_duration(out_path)

    duration = get_duration(out_path)
    print(f"완료: {out_path} (총 {duration:.1f}초)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="manifest로 9:16 Shorts mp4를 조립합니다.")
    parser.add_argument("--manifest", required=True, help="output/manifest_rowN.json 경로")
    parser.add_argument("--script", default=None, help="제목/행 번호용 script JSON (선택)")
    parser.add_argument("--out", default=None, help="출력 mp4 경로 (기본: output/final_rowN.mp4)")
    args = parser.parse_args()
    assemble_from_manifest(args.manifest, script_path=args.script, out_path=args.out)


if __name__ == "__main__":
    main()
