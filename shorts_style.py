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


def wrap_korean(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """공백이 적은 한국어 제목을 픽셀 폭 기준으로 줄바꿈."""
    from PIL import Image, ImageDraw

    probe = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(probe)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            bbox = draw.textbbox((0, 0), trial, font=font)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines or [str(text)]
