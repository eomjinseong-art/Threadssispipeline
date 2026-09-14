"""쇼츠 영상 공통 스타일 (9:16, 샘플 Shorts와 같은 시각 언어)."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 25
AUDIO_RATE = 44100
AUDIO_CHANNELS = 2

# 샘플 Shorts의 밝은 종이 배경에 맞춤
BG_COLOR = (246, 246, 244)
INTRO_BG = (0, 0, 0)
INTRO_FG = (255, 255, 255)
INTRO_DURATION = 2.2

SAFE_TOP = 260
SAFE_BOTTOM = VIDEO_HEIGHT - 320
SAFE_LEFT = 100
SAFE_RIGHT = VIDEO_WIDTH - 100

TEXT_COLOR_ASS = "&H001E1E1E"
LABEL_COLOR = (140, 140, 135)

MAX_DURATION_SEC = 59.5

BGM_CANDIDATES = (
    "assets/bgm.mp3",
    "assets/bgm.wav",
    "assets/bgm.m4a",
    "assets/bgm.aac",
)

REPO_ROOT = Path(__file__).resolve().parent

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    str(REPO_ROOT / "assets" / "subtitle.ttf"),
    str(REPO_ROOT / "assets" / "fonts" / "subtitle.ttf"),
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
]


def output_dir() -> Path:
    path = REPO_ROOT / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def script_path_for_row(row_index: int | str) -> str:
    return str(output_dir() / f"script_row{row_index}.json")


def manifest_path_for_row(row_index: int | str) -> str:
    return str(output_dir() / f"manifest_row{row_index}.json")


def segments_dir_for_row(row_index: int | str) -> str:
    return str(output_dir() / f"segments_row{row_index}")


def final_path_for_row(row_index: int | str) -> str:
    return str(output_dir() / f"final_row{row_index}.mp4")


def thumbnail_path_for_row(row_index: int | str) -> str:
    return str(output_dir() / f"thumbnail_row{row_index}.png")


def find_bgm_path() -> str | None:
    for candidate in BGM_CANDIDATES:
        path = REPO_ROOT / candidate if not os.path.isabs(candidate) else Path(candidate)
        if path.is_file() and path.stat().st_size > 0:
            return str(path)
    return None


def resolve_korean_font() -> tuple[str, str]:
    """한글 TTF 경로와 ASS Fontname을 반환한다.

    Ubuntu Actions: NanumGothic / 로컬: assets/subtitle.ttf (NanumGothic) /
    Windows: 맑은 고딕.
    """
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            family = "NanumGothic"
            lower = path.replace("\\", "/").lower()
            if "malgun" in lower:
                family = "Malgun Gothic"
            elif "subtitle.ttf" in lower:
                family = "NanumGothic"
            return path, family
    raise SystemExit(
        "한글 TTF 폰트를 찾을 수 없습니다. "
        "Ubuntu에서는 'sudo apt-get install -y fonts-nanum' 을 설치하거나 "
        "assets/subtitle.ttf 가 있는지 확인하세요."
    )


def get_font(size: int) -> ImageFont.FreeTypeFont:
    path, _family = resolve_korean_font()
    return ImageFont.truetype(path, size)


def text_pixel_width(draw, text: str, font: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_korean(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """한국어 제목/본문 줄바꿈.

    공백(어절)에서 먼저 끊고, 한 토큰이 너무 길 때만 음절 단위로 자른다.
    2글자 단어(예: 간섭)를 `간` / `섭` 으로 쪼개 마지막 한글자를 고아로 남기지 않는다.
    """
    from PIL import Image, ImageDraw

    probe = Image.new("RGB", (max(int(max_width), 1), 64), (0, 0, 0))
    draw = ImageDraw.Draw(probe)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        lines.extend(_wrap_paragraph(paragraph, draw, font, max_width))
    return lines or [str(text)]


def _wrap_paragraph(paragraph: str, draw, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if text_pixel_width(draw, paragraph, font) <= max_width:
        return [paragraph]

    words = [w for w in paragraph.split(" ") if w != ""]
    if not words:
        return [paragraph]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_pixel_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if text_pixel_width(draw, word, font) <= max_width:
            current = word
            continue
        broken = _wrap_long_word(word, draw, font, max_width)
        lines.extend(broken[:-1])
        current = broken[-1]
    if current:
        lines.append(current)
    return _fix_orphan_syllables(lines, draw, font, max_width)


def _wrap_long_word(word: str, draw, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    i = 0
    while i < len(word):
        ch = word[i]
        trial = current + ch
        if current and text_pixel_width(draw, trial, font) > max_width:
            rest = word[i:]
            if len(rest) == 1 and len(current) >= 2:
                lines.append(current[:-1])
                current = current[-1] + rest
                break
            if len(current) == 1 and len(rest) == 1:
                current = current + rest
                break
            lines.append(current)
            current = ch
        else:
            current = trial
        i += 1
    if current:
        lines.append(current)
    return lines or [word]


def _fix_orphan_syllables(
    lines: list[str], draw, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """마지막 줄이 한글자이면 앞 줄 끝 글자를 내려 2글자 단어를 유지한다."""
    if len(lines) < 2:
        return lines
    last = lines[-1]
    prev = lines[-2]
    if len(last) != 1 or not prev:
        return lines
    moved = prev[-1] + last
    new_prev = prev[:-1].rstrip()
    if new_prev and text_pixel_width(draw, moved, font) <= max_width:
        lines[-2] = new_prev
        lines[-1] = moved
        return lines
    merged = prev + last
    if text_pixel_width(draw, merged, font) <= max_width:
        return lines[:-2] + [merged]
    return lines
