"""waitmybabe Shorts = EP.67 디자인 전용 렌더러.

기준작: EP.67 '내가 차린 제사상, 시어머니 공으로?' (https://youtube.com/shorts/wxTOaqAf51M).
웜 베이지 배경 + '오늘의 사연 · EP.N' 라벨, 명조체 훅 카드, 흰 스토리 카드(로즈 라인),
단톡방 말풍선, 강조 카드, 공감 질문 카드 + 창작 표기. 45~58초, 1080x1920 30fps.

시트 행마다 손으로 쓴 스펙(`sayeon_specs/*.json`, `topic` = 시트 제목)이 있어야 한다.
스펙이 없으면 렌더·업로드하지 않는다. 다른 디자인으로 대신 올리는 경로는 없다.
"""

from __future__ import annotations

import glob
import json
import os
import sys

from story_format import ensure_curiosity, normalize_title

ROOT = os.path.dirname(os.path.abspath(__file__))
SPECS_DIR = os.path.join(ROOT, "sayeon_specs")
ENGINE_DIR = os.path.join(ROOT, "sayeon_engine")
OUTPUT_DIR = os.path.join(ROOT, "output")
DURATION_RANGE = (45.0, 58.0)


def topic_key(title: str) -> str:
    text = str(title or "").strip()
    if not text:
        return ""
    return normalize_title(ensure_curiosity(text))


def load_specs(specs_dir: str = SPECS_DIR) -> list[tuple[str, dict]]:
    specs = []
    for path in sorted(glob.glob(os.path.join(specs_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        if spec.get("channel") == "sayeon":
            specs.append((path, spec))
    return specs


def find_spec_for_title(title: str, specs_dir: str = SPECS_DIR) -> tuple[str, dict] | tuple[None, None]:
    key = topic_key(title)
    if not key:
        return None, None
    for path, spec in load_specs(specs_dir):
        for candidate in (spec.get("topic"), spec.get("title")):
            if candidate and topic_key(candidate) == key:
                return path, spec
    return None, None


def validate_spec(spec: dict) -> None:
    types = [s.get("type") for s in spec.get("segments", [])]
    if not types or types[0] != "hook" or types[-1] != "question":
        raise ValueError("EP.67 스펙은 hook 으로 시작하고 question 으로 끝나야 합니다.")
    if "chat" not in types or "key" not in types:
        raise ValueError("EP.67 스펙에는 단톡방 말풍선(chat)과 강조 카드(key)가 있어야 합니다.")
    title = spec.get("title", "")
    if "#Shorts" not in title or len(title) > 100:
        raise ValueError("제목에 #Shorts 가 있어야 하고 100자 이하여야 합니다.")
    if "창작" not in spec.get("description", ""):
        raise ValueError("설명란에 창작·각색 표기가 필요합니다.")


REQUIRED_FONT_FILES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
)


def ensure_fonts() -> None:
    """EP.67 디자인 폰트(Noto CJK, Noto Color Emoji). CI 러너에 없으면 apt로 설치한다."""
    missing = [p for p in REQUIRED_FONT_FILES if not os.path.exists(p)]
    if not missing:
        return
    if os.environ.get("GITHUB_ACTIONS") == "true":
        import subprocess

        print("[fonts] Noto CJK / Color Emoji 설치")
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "fonts-noto-cjk", "fonts-noto-color-emoji"], check=True)
        missing = [p for p in REQUIRED_FONT_FILES if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(f"EP.67 디자인 폰트가 없습니다: {missing}")


def render_spec(spec: dict, outdir: str = OUTPUT_DIR) -> tuple[str, float]:
    validate_spec(spec)
    ensure_fonts()
    os.environ.setdefault("SAYEON_WORKDIR", os.path.join(ROOT, ".work"))
    os.environ.setdefault("SAYEON_FONT_DIR", os.path.join(ROOT, "assets", "fonts"))
    if ENGINE_DIR not in sys.path:
        sys.path.insert(0, ENGINE_DIR)
    import sayeon  # noqa: E402  (sayeon_engine/sayeon.py)

    out, total = sayeon.render(spec, outdir)
    lo, hi = DURATION_RANGE
    if not (lo <= total <= hi):
        raise ValueError(f"길이 {total:.1f}s 가 EP.67 기준 {lo:.0f}~{hi:.0f}s 를 벗어났습니다. 스펙을 다듬어 주세요.")
    return out, total


def metadata_from_spec(spec: dict) -> dict:
    return {
        "title": spec["title"],
        "description": spec["description"],
        "tags": list(spec.get("tags") or []),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EP.67 디자인 스펙 하나를 렌더합니다 (업로드 없음).")
    parser.add_argument("spec")
    parser.add_argument("--out", default=OUTPUT_DIR)
    args = parser.parse_args()
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    out, total = render_spec(spec, args.out)
    print(f"{out} {total:.2f}s")


if __name__ == "__main__":
    main()
