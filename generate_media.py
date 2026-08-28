"""
1일 1쇼츠 자동화 파이프라인 - 4단계: 무료 Edge-TTS 기반 음성 파일 생성

ElevenLabs API 크레딧 제약 없이 Microsoft Edge TTS(무료)를 사용하여
output/script_{date}.json 의 narration 전체를 한 번에 낭독하는 음성을 생성한다.
"""

import os
import glob
import json
import asyncio
import datetime as dt
import edge_tts

SCRIPT_PATH_TEMPLATE = "output/script_{date}.json"
NARRATION_AUDIO_TEMPLATE = "output/narration_{date}.mp3"

# 음성 모델 선택 (기본: SunHi - 또렷하고 깔끔한 여성 진행자 톤)
DEFAULT_VOICE = "ko-KR-SunHiNeural"


# ---------------------------------------------------------------------------
# 날짜/파일 찾기
# ---------------------------------------------------------------------------

def find_latest_script_date() -> str:
    paths = glob.glob(SCRIPT_PATH_TEMPLATE.format(date="*"))
    dates = []
    for p in paths:
        # output/script_2026-08-28.json 형태에서 날짜 추출
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
    """Edge-TTS를 이용하여 비동기로 음성을 생성하고 파일로 저장한다."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def synth_audio_edge(text: str, out_path: str, voice: str = DEFAULT_VOICE) -> None:
    """비동기 TTS 함수를 동기식으로 호출하는 래퍼 함수"""
    print(f"Edge-TTS 음성 합성 시작 (목소리: {voice}, 글자 수: {len(text)}자)...")
    asyncio.run(generate_speech_async(text, voice, out_path))
    print(f"음성 파일 생성 완료: {out_path}")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    try:
        date = find_latest_script_date()
        print(f"대상 날짜: {date}")

        script_path = SCRIPT_PATH_TEMPLATE.format(date=date)
        narration_audio_path = NARRATION_AUDIO_TEMPLATE.format(date=date)

        if not os.path.exists(script_path):
            raise FileNotFoundError(f"{script_path} 파일이 존재하지 않습니다.")

        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        narration_text = script.get("narration", "").strip()
        if not narration_text:
            raise ValueError("script.json 내에 narration 텍스트가 비어 있습니다.")

        # 음성 합성 실행
        synth_audio_edge(
            text=narration_text,
            out_path=narration_audio_path,
            voice=DEFAULT_VOICE
        )

        print(f"성공적으로 4단계(음성 생성)가 완료되었습니다: {narration_audio_path}")

    except Exception as e:
        print(f":rotating_light: [generate_media] 음성 생성 실패: {e}")
        raise


if __name__ == "__main__":
    main()
