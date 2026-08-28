"""
1일 1쇼츠 자동화 파이프라인 - 4단계: 무료 Edge-TTS 기반 음성 및 매니페스트 생성

ElevenLabs API 대신 Microsoft Edge TTS(무료)를 사용하여
output/script_{date}.json 의 narration 전체를 한 번에 낭독하는 음성을 생성하고,
전체 음성 길이를 기반으로 turn별 duration 및 image_path를 계산하여
assemble_video.py에서 사용할 output/manifest_{date}.json 을 작성한다.
"""

import os
import glob
import json
import asyncio
import edge_tts
from mutagen.mp3 import MP3
from PIL import Image

SCRIPT_PATH_TEMPLATE = "output/script_{date}.json"
NARRATION_AUDIO_TEMPLATE = "output/narration_{date}.mp3"
MANIFEST_PATH_TEMPLATE = "output/manifest_{date}.json"

# 기본 배경 이미지 경로
DEFAULT_IMAGE_PATH = "assets/background.png"

# 음성 모델 선택 (또렷하고 깔끔한 한국어 여성 진행자 톤)
DEFAULT_VOICE = "ko-KR-SunHiNeural"


# ---------------------------------------------------------------------------
# 필수 이미지 보장 (없으면 기본 이미지 자동 생성)
# ---------------------------------------------------------------------------

def ensure_default_image_exists(image_path: str = DEFAULT_IMAGE_PATH) -> None:
    """배경 이미지 파일이 없으면 1080x1920 단색 배경을 자동 생성한다."""
    if not os.path.exists(image_path):
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        img = Image.new("RGB", (1080, 1920), color=(18, 18, 24))
        img.save(image_path)
        print(f"기본 배경 이미지 자동 생성 완료: {image_path}")


# ---------------------------------------------------------------------------
# 날짜/파일 찾기
# ---------------------------------------------------------------------------

def find_latest_script_date() -> str:
    paths = glob.glob(SCRIPT_PATH_TEMPLATE.format(date="*"))
    dates = []
    for p in paths:
        basename = os.path.basename(p)
        date_str = basename.replace("script_", "").replace(".json", "")
        if len(date_str) == 10:  # YYYY-MM-DD
            dates.append(date_str)
            
    if not dates:
        raise FileNotFoundError(
            "output/script_*.json 파일을 찾을 수 없습니다. "
            "fetch_script.py를 먼저 실행했는지 확인하세요."
        )
    return sorted(dates)[-1]


# ---------------------------------------------------------------------------
# Edge-TTS 음성 합성
# ---------------------------------------------------------------------------

async def generate_speech_async(text: str, voice: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def synth_audio_edge(text: str, out_path: str, voice: str = DEFAULT_VOICE) -> None:
    print(f"Edge-TTS 음성 합성 시작 (목소리: {voice}, 글자 수: {len(text)}자)...")
    asyncio.run(generate_speech_async(text, voice, out_path))
    print(f"음성 파일 생성 완료: {out_path}")


# ---------------------------------------------------------------------------
# 오디오 길이 기반 Turn별 Duration 및 Image Path 계산
# ---------------------------------------------------------------------------

def process_turns(audio_path: str, turns: list[dict]) -> list[dict]:
    """전체 음성 길이를 측정하여 duration을 분배하고, image_path를 주입한다."""
    audio = MP3(audio_path)
    total_duration = audio.info.length  # 전체 오디오 길이 (초)

    total_weight_len = sum(len(t.get("weight_text", t.get("line", ""))) for t in turns)
    if total_weight_len == 0:
        total_weight_len = 1

    for t in turns:
        text_len = len(t.get("weight_text", t.get("line", "")))
        t["duration"] = (text_len / total_weight_len) * total_duration
        
        if "image_path" not in t or not t["image_path"] or not os.path.exists(t["image_path"]):
            t["image_path"] = DEFAULT_IMAGE_PATH

    return turns


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    try:
        ensure_default_image_exists()

        date = find_latest_script_date()
        print(f"대상 날짜: {date}")

        script_path = SCRIPT_PATH_TEMPLATE.format(date=date)
        narration_audio_path = NARRATION_AUDIO_TEMPLATE.format(date=date)
        manifest_path = MANIFEST_PATH_TEMPLATE.format(date=date)

        if not os.path.exists(script_path):
            raise FileNotFoundError(f"{script_path} 파일이 존재하지 않습니다.")

        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        narration_text = script.get("narration", "").strip()
        if not narration_text:
            raise ValueError("script.json 내에 narration 텍스트가 비어 있습니다.")

        # 1. 음성 파일 생성
        synth_audio_edge(
            text=narration_text,
            out_path=narration_audio_path,
            voice=DEFAULT_VOICE
        )

        # 2. turns 데이터 가공 (duration 및 image_path 주입)
        turns = script.get("turns", [])
        processed_turns = process_turns(narration_audio_path, turns)

        # 3. assemble_video.py 호환용 manifest_*.json 파일 생성 (narration_audio 및 audio_path 둘 다 포함)
        manifest_data = {
            "date": date,
            "script_path": script_path,
            "narration_audio": narration_audio_path,  # assemble_video.py 필수 키
            "audio_path": narration_audio_path,       # 하위 호환성 유지용
            "title": script.get("title", ""),
            "turns": processed_turns
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        print(f"매니페스트 파일 생성 완료: {manifest_path}")
        print("성공적으로 4단계(음성 및 매니페스트 생성)가 완료되었습니다.")

    except Exception as e:
        print(f":rotating_light: [generate_media] 음성 생성 실패: {e}")
        raise


if __name__ == "__main__":
    main()
