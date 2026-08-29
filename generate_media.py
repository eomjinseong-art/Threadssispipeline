"""
1일 1쇼츠 자동화 파이프라인 - 2단계: 음성/이미지 생성 (미니멀 3슬라이드 버전)

fetch_script.py가 만든 output/script_{date}.json의 슬라이드 3장마다:
  1) edge-tts(무료, Microsoft)로 그 슬라이드의 narration_text를 음성으로 만들고
  2) 그 슬라이드의 display_text를 화면 전체 카드 이미지로 PIL 렌더링
슬라이드당 audio_path/image_path/duration을 채운 manifest_{date}.json을 만든다.

[미니멀 설계] 슬라이드가 3장뿐이라 API 호출도 3번(전부 무료)뿐이고, 각
슬라이드는 그 자신의 실제 음성 길이를 그대로 쓰므로(카톡 UI 때처럼 turn이
많아서 비율 계산하던 방식과 달리) 타이밍 어긋날 일이 없다. 화면도 애니메이션
없이 카드 하나가 통째로 떠 있다가 다음 카드로 바뀌는 방식이라 렌더링 로직도
단순하다.

필요 패키지:
  pip install edge-tts Pillow --break-system-packages

필요 폰트(한글 렌더링):
  워크플로에 sudo apt-get install -y fonts-nanum 필요

edge-tts 목소리를 바꾸고 싶으면 VOICE 상수만 수정하면 된다.
목록 확인: edge-tts --list-voices | grep ko-KR
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
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT

BG_COLOR = (250, 250, 248)
TEXT_COLOR = (30, 30, 30)
LABEL_COLOR = (140, 140, 135)

SLIDE_LABELS = {
    "story": "사연",
    "reactions": "언니들의 반응",
    "question": "여러분의 생각은?",
}

# 슬라이드 종류별로 화자 라벨(현실언니/공감언니/폭주언니) 색을 다르게 표시
SPEAKER_COLORS = {
    "현실언니": (55, 138, 221),
    "공감언니": (99, 153, 34),
    "폭주언니": (226, 75, 74),
}

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def get_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    raise SystemExit(
        "한글 TTF 폰트를 찾을 수 없습니다. "
        "워크플로에 'sudo apt-get install -y fonts-nanum' 스텝이 있는지 확인하세요."
    )


def get_audio_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {result.stderr}")
    return float(result.stdout.strip())


def wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split(" ")
    lines, current = [], ""
    for w in words:
        trial = f"{current} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def render_slide(slide: dict, font_body, font_label, line_height: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    label = SLIDE_LABELS.get(slide["type"], "")
    if label:
        draw.text((SAFE_LEFT, SAFE_TOP), label, font=font_label, fill=LABEL_COLOR)

    body_top = SAFE_TOP + 80
    if slide["type"] == "reactions":
        paragraphs = slide["display_text"].split("\n\n")
    else:
        paragraphs = slide["display_text"].split("\n")

    # 각 문단(화자별 대사 등)을 줄바꿈까지 반영해서 라인 목록으로 변환
    all_lines: list[tuple[str, tuple]] = []  # (텍스트, 색상)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        speaker_color = TEXT_COLOR
        for speaker, color in SPEAKER_COLORS.items():
            if para.startswith(speaker + ":"):
                speaker_color = color
                break
        wrapped = wrap_text(draw, para, font_body, SAFE_WIDTH)
        for line in wrapped:
            all_lines.append((line, speaker_color))
        all_lines.append(("", TEXT_COLOR))  # 문단 사이 여백 한 줄

    if all_lines and all_lines[-1][0] == "":
        all_lines.pop()

    total_h = len(all_lines) * line_height
    available_h = SAFE_BOTTOM - body_top
    y = body_top + max((available_h - total_h) // 2, 0)

    for line, color in all_lines:
        if line:
            line_w = draw.textlength(line, font=font_body)
            x = SAFE_LEFT + (SAFE_WIDTH - line_w) // 2
            draw.text((x, y), line, font=font_body, fill=color)
        y += line_height

    return img


async def synth_audio_async(text: str, out_path: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(out_path)


def synth_audio(text: str, out_path: str) -> None:
    asyncio.run(synth_audio_async(text, out_path))


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
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    font_body = get_font(FONT_CANDIDATES_BOLD, 52)
    font_label = get_font(FONT_CANDIDATES_BOLD, 32)
    line_height = 70

    manifest_slides = []
    total_duration = 0.0

    for slide in script["slides"]:
        i = slide["index"]
        print(f"[{i + 1}/{len(script['slides'])}] ({slide['type']}) {slide['narration_text'][:30]}...")

        audio_path = os.path.join(audio_dir, f"{i:02d}.mp3")
        synth_audio(slide["narration_text"], audio_path)
        duration = get_audio_duration(audio_path)
        total_duration += duration

        image_path = os.path.join(image_dir, f"{i:02d}.png")
        frame = render_slide(slide, font_body, font_label, line_height)
        frame.save(image_path)

        manifest_slides.append({
            "index": i,
            "type": slide["type"],
            "audio_path": audio_path,
            "image_path": image_path,
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
