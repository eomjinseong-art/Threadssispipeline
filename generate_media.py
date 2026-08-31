"""
1일 1쇼츠 자동화 파이프라인 - 2단계: 음성/자막 생성 (타이핑 자막 버전)

fetch_script.py가 만든 output/script_{date}.json의 슬라이드 3장마다:
  1) edge-tts로 narration_text를 음성으로 만들면서, 무료로 제공되는 단어별
     타이밍(Word Boundary)도 같이 받는다.
  2) 그 타이밍 그대로 "말하는 대로 글자가 늘어나는" 타이핑 자막(.ass) 파일을
     만든다. 텍스트를 미리 그린 정적 이미지 대신, 라벨만 있는 빈 배경
     이미지 + 실시간 자막(ffmpeg의 ass 필터)으로 렌더링한다.

[언니들 반응 슬라이드의 색상 처리] 이 슬라이드는 "현실언니는 이렇게
말합니다. ... 공감언니는 이렇게 말합니다. ... 그리고 폭주언니는 이렇게
말합니다. ..." 하나의 문장을 통째로 낭독하므로, 그 안에서 각 단어가
누구 구간에 속하는지(현실/공감/폭주) 텍스트 위치로 판별해서 자막 색을
그 화자 색으로 바꿔가며 표시한다.

필요 패키지:
  pip install edge-tts Pillow --break-system-packages

필요 폰트(한글 렌더링):
  워크플로에 sudo apt-get install -y fonts-nanum 필요

edge-tts 목소리/속도를 바꾸고 싶으면 VOICE/RATE 상수만 수정하면 된다.
"""

import os
import json
import asyncio
import subprocess
import datetime as dt

import edge_tts
from PIL import Image, ImageDraw, ImageFont

SCRIPT_PATH_TEMPLATE = "output/script_{date}.json"
MANIFEST_PATH_TEMPLATE = "output/manifest_{date}.json"
SEGMENTS_DIR_TEMPLATE = "output/segments_{date}"

VOICE = "ko-KR-SunHiNeural"  # 무료 한국어 여성 음성(Microsoft edge-tts)
RATE = "+15%"  # 기본 속도보다 15% 빠르게 - 쇼츠 특성상 속도감 있게

W, H = 1080, 1920
SAFE_TOP = 260
SAFE_BOTTOM = H - 320
SAFE_LEFT = 100
SAFE_RIGHT = W - 100

BG_COLOR = (250, 250, 248)
TEXT_COLOR_ASS = "&H001E1E1E"    # 기본 글자색(검정에 가까움), ASS는 BGR 순서
LABEL_COLOR = (140, 140, 135)

SLIDE_LABELS = {"story": "사연", "reactions": "언니들의 반응", "question": "여러분의 생각은?"}

# ASS 색상은 &HBBGGRR 형식(BGR 순서, RGB 반대)
SPEAKER_ASS_COLORS = {
    "현실언니": "&H00DD8A37",  # RGB(55,138,221) -> BGR
    "공감언니": "&H00229963",  # RGB(99,153,34) -> BGR
    "폭주언니": "&H004A4BE2",  # RGB(226,75,74) -> BGR
}

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


def get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES_BOLD:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    raise SystemExit(
        "한글 TTF 폰트를 찾을 수 없습니다. "
        "워크플로에 'sudo apt-get install -y fonts-nanum' 스텝이 있는지 확인하세요."
    )


def seconds_to_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


async def synth_with_timing(text: str, audio_out_path: str) -> list[dict]:
    """edge-tts로 음성을 만들면서 단어별 타이밍(WordBoundary)도 같이 받는다."""
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    word_boundaries = []
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
    """언니들 반응 슬라이드 안에서 각 화자 구간이 몇 번째 글자부터 시작하는지 찾는다.
    [(시작 인덱스, 화자이름), ...] 형태, 시작 인덱스 오름차순."""
    segments = []
    for speaker in SPEAKER_ASS_COLORS:
        idx = narration_text.find(speaker)
        if idx != -1:
            segments.append((idx, speaker))
    segments.sort(key=lambda x: x[0])
    return segments


def color_for_position(pos: int, segments: list[tuple[int, str]]) -> str | None:
    """narration_text 안에서 pos 위치가 어느 화자 구간에 속하는지로 ASS 색상 반환."""
    current_speaker = None
    for start, speaker in segments:
        if pos >= start:
            current_speaker = speaker
        else:
            break
    return SPEAKER_ASS_COLORS.get(current_speaker) if current_speaker else None


MAX_ACCUMULATED_CHARS = 90  # 이 글자수를 넘으면 오래된 단어부터 화면에서 밀어냄(오버플로 방지)


def build_typing_ass(
    word_boundaries: list[dict],
    total_duration: float,
    narration_text: str,
    slide_type: str,
    out_path: str,
) -> None:
    """단어가 하나씩 늘어나는 타이핑 효과 자막(.ass) 파일 생성.
    slide_type이 'reactions'면 화자 구간별로 글자색을 바꿔가며 표시한다.
    누적된 글자수가 MAX_ACCUMULATED_CHARS를 넘으면, 실제 카톡처럼 오래된
    단어부터 화면 밖으로 밀어내서(슬라이딩 윈도우) 화면 오버플로를 막는다."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Malgun Gothic,54,{TEXT_COLOR_ASS},&H000000FF,&H00FAFAFA,&H00FAFAFA,-1,0,0,0,100,100,0,0,1,0,0,5,{SAFE_LEFT},{W - SAFE_RIGHT},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    segments = find_speaker_segments(narration_text) if slide_type == "reactions" else []

    accumulated_parts = []  # (word_text, ass_color_or_None) 리스트
    cursor = 0

    for i, wb in enumerate(word_boundaries):
        word = wb["text"]
        found_at = narration_text.find(word, cursor)
        pos = found_at if found_at != -1 else cursor
        cursor = pos + len(word)

        color = color_for_position(pos, segments) if segments else None
        accumulated_parts.append((word, color))

        # 슬라이딩 윈도우: 누적 글자수가 한도를 넘으면 오래된 단어부터 제거
        while sum(len(w) + 1 for w, _ in accumulated_parts) > MAX_ACCUMULATED_CHARS and len(accumulated_parts) > 1:
            accumulated_parts.pop(0)

        start = wb["offset"]
        end = word_boundaries[i + 1]["offset"] if i + 1 < len(word_boundaries) else total_duration

        text_pieces = []
        last_color = None
        for w, c in accumulated_parts:
            if c != last_color:
                text_pieces.append(f"{{\\c{c if c else TEXT_COLOR_ASS}&}}")
                last_color = c
            safe_w = w.replace("{", "").replace("}", "")
            text_pieces.append(safe_w + " ")
        full_text = "".join(text_pieces).strip()

        lines.append(
            f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
            f"Default,,0,0,0,,{full_text}\n"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def build_background(slide_type: str, out_path: str) -> None:
    """텍스트 없이 라벨만 있는 배경 카드 - 본문 자막은 ffmpeg가 실시간으로 그린다."""
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    label = SLIDE_LABELS.get(slide_type, "")
    if label:
        font_label = get_font(32)
        draw.text((SAFE_LEFT, SAFE_TOP), label, font=font_label, fill=LABEL_COLOR)
    img.save(out_path)


def get_audio_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {result.stderr}")
    return float(result.stdout.strip())


def main():
    today = dt.date.today().isoformat()
    script_path = SCRIPT_PATH_TEMPLATE.format(date=today)
    if not os.path.exists(script_path):
        raise SystemExit(f"{script_path} 가 없습니다. fetch_script.py를 먼저 실행하세요.")

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    segments_dir = SEGMENTS_DIR_TEMPLATE.format(date=today)
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
        duration = get_audio_duration(audio_path)
        total_duration += duration

        ass_path = os.path.join(ass_dir, f"{i:02d}.ass")
        build_typing_ass(word_boundaries, duration, slide["narration_text"], slide["type"], ass_path)

        image_path = os.path.join(image_dir, f"{i:02d}.png")
        build_background(slide["type"], image_path)

        manifest_slides.append({
            "index": i,
            "type": slide["type"],
            "audio_path": audio_path,
            "image_path": image_path,
            "ass_path": ass_path,
            "duration": duration,
        })

    print(f"전체 낭독 길이: {total_duration:.1f}초")

    manifest = {
        "date": today,
        "title": script.get("title"),
        "total_duration": total_duration,
        "slides": manifest_slides,
    }
    out_path = MANIFEST_PATH_TEMPLATE.format(date=today)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"완료: {out_path}")


if __name__ == "__main__":
    main()
