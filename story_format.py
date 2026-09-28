"""숏폼 제목·훅·질문 정리.

유튜브 제목은 갈등과 호기심으로 시작하고 EP 번호로 시작하지 않는다.
채널 이름은 업로드 단계에서 끝에 붙인다.
"""

from __future__ import annotations

import re

DEFAULT_QUESTION = "여러분이라면 참으실 수 있나요?"
CHANNEL_SUFFIX = " | waitmybabe"
TITLE_MAX_LEN = 100

_EP_PREFIX = re.compile(r"^\s*EP\.?\s*\d+\s*", re.IGNORECASE)
_CHANNEL_SUFFIX = re.compile(r"\s*\|\s*waitmybabe\s*$", re.IGNORECASE)
_SHORTS_TAG = re.compile(r"\s*#shorts\s*$", re.IGNORECASE)
_WS = re.compile(r"\s+")


def strip_leading_ep(title: str) -> str:
    return _EP_PREFIX.sub("", str(title or "")).strip()


def ensure_curiosity(title: str) -> str:
    """갈등 제목 뒤에 호기심을 붙인다. 이미 질문이면 그대로 둔다."""
    text = strip_leading_ep(title)
    text = _CHANNEL_SUFFIX.sub("", text).strip()
    text = _SHORTS_TAG.sub("", text).strip()
    if not text:
        return "이 상황, 결말은?"
    if "결말" in text or "?" in text or "？" in text:
        return text
    return f"{text}, 결말은?"


def normalize_title(title: str) -> str:
    """중복 제목 비교. EP 접두·채널 접미·#Shorts·연속 공백은 무시한다."""
    text = strip_leading_ep(title)
    text = _CHANNEL_SUFFIX.sub("", text)
    text = _SHORTS_TAG.sub("", text)
    text = _WS.sub(" ", text).strip()
    return text.casefold()


def finish_sentence(line: str) -> str:
    """줄 끝에 문장 부호가 없으면 붙인다. 대사가 다음 문장에 붙지 않게."""
    text = str(line or "").strip()
    if not text:
        return text
    closer = ""
    body = text
    if text[-1] in "\"”’'":
        closer = text[-1]
        body = text[:-1].rstrip()
    if not body:
        return text
    if body[-1] not in ".?!？!！…":
        body += "."
    return body + closer


def is_spoken_hook(line: str) -> bool:
    """첫 줄이 화면 훅으로 쓸 만큼 구체적인 한 문장인지."""
    text = str(line or "").strip().strip("\"“”")
    if len(text) < 18:
        return False
    return text[-1] in "요다까죠네?？!！.…"


def choose_hook(title: str, story_lines: list[str], adaptation_hook: str | None = None) -> str:
    if adaptation_hook and str(adaptation_hook).strip():
        return str(adaptation_hook).strip()
    if story_lines and is_spoken_hook(story_lines[0]):
        return story_lines[0].strip().strip("\"“”")
    return ensure_curiosity(title)


def youtube_title(raw_title: str) -> str:
    """업로드 제목. EP는 앞에 두지 않고, 들어가면 채널 이름을 끝에 붙인다."""
    title = ensure_curiosity(raw_title)
    channel = CHANNEL_SUFFIX
    shorts = " #Shorts"
    room = TITLE_MAX_LEN - len(shorts)
    if len(title) + len(channel) <= room:
        title = title + channel
    if len(title) > room:
        title = title[:room].rstrip()
    return (title + shorts)[:TITLE_MAX_LEN]


def ep_to_int(raw) -> int | None:
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
