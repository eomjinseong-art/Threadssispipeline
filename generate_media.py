"""
1일 1쇼츠 자동화 파이프라인 - 2단계: 음성/자막 생성 (타이핑 자막 버전)

fetch_script.py가 만든 output/script_row{N}.json 의 슬라이드 3장마다:
  1) edge-tts로 narration_text를 음성으로 만들면서, 단어별 타이밍(WordBoundary)도
     같이 받는다. edge-tts 7.x 기본값은 SentenceBoundary 라서 ASS Dialogue가
     비게 되므로 반드시 WordBoundary를 요청한다.
  2) 그 타이밍 그대로 "말하는 대로 글자가 늘어나는" 타이핑 자막(.ass) 파일을
     만든다. 텍스트를 미리 그린 정적 이미지 대신, 라벨만 있는 빈 배경
     이미지 + 실시간 자막(ffmpeg의 ass 필터)으로 렌더링한다.

[언니들 반응 슬라이드의 색상 처리] 이 슬라이드는 하나의 문장을 통째로
낭독하므로, 그 안에서 각 단어가 누구 구간에 속하는지 텍스트 위치로
판별해서 자막 색을 그 화자 색으로 바꿔가며 표시한다.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import subprocess

import edge_tts
from PIL import Image, ImageDraw

from shorts_style import (
    BG_COLOR,
    LABEL_COLOR,
    SAFE_LEFT,
    SAFE_RIGHT,
    SAFE_TOP,
    TEXT_COLOR_ASS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    get_font,
    manifest_path_for_row,
    resolve_korean_font,
    segments_dir_for_row,
)

VOICE = "ko-KR-SunHiNeural"
RATE = "+15%"
# edge-tts 7.x 기본값은 SentenceBoundary. 타이핑 자막을 만들려면 반드시 WordBoundary.
EDGE_TTS_BOUNDARY = "WordBoundary"

SLIDE_LABELS = {"story": "사연", "reactions": "언니들의 반응", "question": "여러분의 생각은?"}

SPEAKER_ASS_COLORS = {
    "현실언니": "&H00DD8A37",
    "공감언니": "&H00229963",
    "폭주언니": "&H004A4BE2",
}

# 화면에는 2~3줄 가라오케 창만 둔다. 슬라이드 전체를 한 덩어리로 쌓지 않는다.
MAX_CAPTION_LINES = 3
MAX_CHARS_PER_LINE = 15
SENTENCE_END_CHARS = set(".?!。…")


def make_communicate(text: str) -> edge_tts.Communicate:
    """WordBoundary를 명시적으로 요청한다. 구버전은 해당 kwargs가 없을 수 있다."""
    kwargs: dict = {"rate": RATE}
    try:
        params = inspect.signature(edge_tts.Communicate.__init__).parameters
        if "boundary" in params:
            kwargs["boundary"] = EDGE_TTS_BOUNDARY
    except (TypeError, ValueError):
        kwargs["boundary"] = EDGE_TTS_BOUNDARY
    return edge_tts.Communicate(text, VOICE, **kwargs)


def seconds_to_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


async def synth_with_timing(text: str, audio_out_path: str) -> list[dict]:
    """edge-tts로 음성을 만들면서 단어별 타이밍(WordBoundary)도 같이 받는다."""
    communicate = make_communicate(text)
    word_boundaries: list[dict] = []
    with open(audio_out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000,
                })
    return word_boundaries


def synth_audio_sync(text: str, audio_out_path: str) -> list[dict]:
    return asyncio.run(synth_with_timing(text, audio_out_path))


def find_speaker_segments(narration_text: str) -> list[tuple[int, str]]:
    """언니들 반응 슬라이드 안에서 각 화자 구간이 몇 번째 글자부터 시작하는지 찾는다."""
    segments = []
    for speaker in SPEAKER_ASS_COLORS:
        idx = narration_text.find(speaker)
        if idx != -1:
            segments.append((idx, speaker))
    segments.sort(key=lambda x: x[0])
    return segments


def color_for_position(pos: int, segments: list[tuple[int, str]]) -> str | None:
    current_speaker = None
    for start, speaker in segments:
        if pos >= start:
            current_speaker = speaker
        else:
            break
    return SPEAKER_ASS_COLORS.get(current_speaker) if current_speaker else None


def ass_font_name() -> str:
    _path, family = resolve_korean_font()
    return family


def ends_sentence(word: str) -> bool:
    w = (word or "").strip()
    return bool(w) and w[-1] in SENTENCE_END_CHARS


def split_word_no_orphan(word: str, max_chars: int) -> list[str]:
    if len(word) <= max_chars:
        return [word]
    chunks: list[str] = []
    i = 0
    while i < len(word):
        remaining = len(word) - i
        if remaining <= max_chars:
            tail = word[i:]
            if len(tail) == 1 and chunks and chunks[-1]:
                prev = chunks[-1]
                chunks[-1] = prev[:-1]
                tail = prev[-1] + tail
                if not chunks[-1]:
                    chunks.pop()
            chunks.append(tail)
            break
        take = max_chars
        if remaining - take == 1 and take >= 2:
            take -= 1
        chunks.append(word[i:i + take])
        i += take
    return [c for c in chunks if c]


def wrap_caption_lines(text: str, max_chars: int = MAX_CHARS_PER_LINE, max_lines: int = MAX_CAPTION_LINES) -> list[str]:
    """어절 우선 줄바꿈 후 마지막 max_lines 줄만 남긴다."""
    words = [w for w in text.split(" ") if w]
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        if len(word) <= max_chars:
            current = word
        else:
            pieces = split_word_no_orphan(word, max_chars)
            lines.extend(pieces[:-1])
            current = pieces[-1]
    if current:
        lines.append(current)
    if len(lines) >= 2 and len(lines[-1]) == 1 and lines[-2]:
        prev = lines[-2]
        lines[-2] = prev[:-1].rstrip()
        lines[-1] = prev[-1] + lines[-1]
        if not lines[-2]:
            lines.pop(-2)
    return lines[-max_lines:]


def format_caption_ass(parts: list[tuple[str, str | None]]) -> str:
    """가라오케 창: 최대 2~3줄. 화자가 바뀌면 창을 비우므로 색은 보통 하나."""
    plain = " ".join(w.replace("{", "").replace("}", "") for w, _c in parts).strip()
    wrapped = wrap_caption_lines(plain)
    if not wrapped:
        return ""
    body = r"\N".join(wrapped)
    colors = {c for _w, c in parts if c}
    if len(colors) == 1:
        return f"{{\\c{next(iter(colors))}&}}{body}"
    return body


def build_typing_ass(
    word_boundaries: list[dict],
    total_duration: float,
    narration_text: str,
    slide_type: str,
    out_path: str,
) -> None:
    """말하는 단어만 2~3줄 창에 쌓고, 문장/화자가 바뀌면 지운다.

    Alignment 8(상단 고정)이라 글자가 늘어도 화면 가운데로 다시 모이지 않는다.
    """
    font_name = ass_font_name()
    # Alignment 8 = 위 가운데. MarginV 는 라벨(사연) 아래.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},54,{TEXT_COLOR_ASS},&H000000FF,&H00FAFAFA,&H00FAFAFA,-1,0,0,0,100,100,0,0,1,0,0,8,{SAFE_LEFT},{VIDEO_WIDTH - SAFE_RIGHT},520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    segments = find_speaker_segments(narration_text) if slide_type == "reactions" else []

    accumulated_parts: list[tuple[str, str | None]] = []
    cursor = 0
    prev_color: str | None = None
    clear_before_next = False

    for i, wb in enumerate(word_boundaries):
        word = wb["text"]
        found_at = narration_text.find(word, cursor)
        pos = found_at if found_at != -1 else cursor
        cursor = pos + len(word)

        color = color_for_position(pos, segments) if segments else None
        if clear_before_next:
            accumulated_parts = []
            clear_before_next = False
        if (
            slide_type == "reactions"
            and accumulated_parts
            and color is not None
            and prev_color is not None
            and color != prev_color
        ):
            accumulated_parts = []

        accumulated_parts.append((word, color))
        prev_color = color if color is not None else prev_color

        start = wb["offset"]
        end = word_boundaries[i + 1]["offset"] if i + 1 < len(word_boundaries) else total_duration

        full_text = format_caption_ass(accumulated_parts)
        if not full_text:
            continue

        lines.append(
            f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
            f"Default,,0,0,0,,{{\\an8}}{full_text}\n"
        )

        if ends_sentence(word):
            clear_before_next = True

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def build_background(slide_type: str, out_path: str) -> None:
    """텍스트 없이 라벨만 있는 배경 카드 - 본문 자막은 ffmpeg가 실시간으로 그린다."""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    label = SLIDE_LABELS.get(slide_type, "")
    if label:
        font_label = get_font(32)
        draw.text((SAFE_LEFT, SAFE_TOP), label, font=font_label, fill=LABEL_COLOR)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)


def get_audio_duration(path: str) -> float:
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


def generate_media(script_path: str) -> str:
    """명시된 script JSON으로 음성/자막/배경을 만들고 manifest 경로를 반환한다."""
    if not os.path.exists(script_path):
        raise SystemExit(f"{script_path} 가 없습니다. fetch_script.py를 먼저 실행하세요.")

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    row_index = script.get("row_index")
    if row_index is None:
        raise SystemExit(
            "script JSON에 row_index가 없습니다. "
            "날짜 glob(script_YYYY-MM-DD.json) 대신 script_row{{N}}.json 을 사용하세요."
        )

    segments_dir = segments_dir_for_row(row_index)
    audio_dir = os.path.join(segments_dir, "audio")
    image_dir = os.path.join(segments_dir, "images")
    ass_dir = os.path.join(segments_dir, "ass")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(ass_dir, exist_ok=True)

    manifest_slides = []
    total_duration = 0.0

    for slide in script["slides"]:
        i = slide["index"]
        print(f"[{i + 1}/{len(script['slides'])}] ({slide['type']}) 음성+타이밍 생성 중...")

        audio_path = os.path.join(audio_dir, f"{i:02d}.mp3")
        word_boundaries = synth_audio_sync(slide["narration_text"], audio_path)
        if not word_boundaries:
            raise RuntimeError(
                "edge-tts가 WordBoundary를 반환하지 않았습니다. "
                "Communicate(..., boundary='WordBoundary') 가 적용됐는지 확인하세요. "
                "7.x 기본값 SentenceBoundary 이면 ASS Dialogue 줄이 비어 자막이 안 나옵니다."
            )
        duration = get_audio_duration(audio_path)
        total_duration += duration

        ass_path = os.path.join(ass_dir, f"{i:02d}.ass")
        build_typing_ass(
            word_boundaries, duration, slide["narration_text"], slide["type"], ass_path
        )
        with open(ass_path, encoding="utf-8") as ass_file:
            dialogue_lines = [
                line for line in ass_file if line.startswith("Dialogue:")
            ]
        nonempty = [
            line for line in dialogue_lines
            if line.rsplit(",", 1)[-1].strip()
        ]
        if not nonempty:
            raise RuntimeError(
                f"슬라이드 {i} ASS Dialogue 텍스트가 비어 있습니다. "
                "WordBoundary 타이밍이 자막으로 변환되지 않았습니다."
            )

        image_path = os.path.join(image_dir, f"{i:02d}.png")
        build_background(slide["type"], image_path)

        manifest_slides.append({
            "index": i,
            "type": slide["type"],
            "audio_path": audio_path,
            "image_path": image_path,
            "ass_path": ass_path,
            "duration": duration,
            "word_boundary_count": len(word_boundaries),
        })

    print(f"전체 낭독 길이: {total_duration:.1f}초")

    manifest = {
        "date": script.get("date"),
        "row_index": row_index,
        "ep": script.get("ep"),
        "title": script.get("title"),
        "script_path": os.path.abspath(script_path),
        "total_duration": total_duration,
        "slides": manifest_slides,
    }
    out_path = manifest_path_for_row(row_index)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"완료: {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="사연 스크립트로 TTS+타이핑 자막을 생성합니다.")
    parser.add_argument("--script", required=True, help="output/script_rowN.json 경로")
    args = parser.parse_args()
    generate_media(args.script)


if __name__ == "__main__":
    main()
