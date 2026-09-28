"""waitmybabe 새 반전 사연 카탈로그.

topics/w01_w21.csv 는 시트에 없는 원작이다.
topics/adapted_10.csv 는 이미 있는 EP를 숏폼 생성 때 반전으로 각색하는 덮개다.
같은 EP가 시트에 있으면 행을 또 추가하지 않는다.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from story_format import (
    DEFAULT_QUESTION,
    ensure_curiosity,
    ep_to_int,
    finish_sentence,
    normalize_title,
)

REPO_ROOT = Path(__file__).resolve().parent
W_CSV = REPO_ROOT / "topics" / "w01_w21.csv"
ADAPTED_CSV = REPO_ROOT / "topics" / "adapted_10.csv"

_REAL = (
    "증거가 남으면 그 다음 말이 짧아져요.",
    "감정 대신 사실을 꺼내서 끝이 난 거예요.",
    "그 한 수가 자리를 되돌렸어요.",
)
_EMPATHY = (
    "그 말, 집에 와서도 남았을 거예요.",
    "혼자 삼키기엔 너무 구체적인 선 넘음이에요.",
    "그 자리의 공기, 충분히 상상이 돼요.",
)
_RAGE = (
    "다음엔 그 선, 더 빨리 그어도 됩니다.",
    "가족이라는 말로 넘길 일은 아니었어요.",
    "정중하게 되돌려 준 거, 잘한 거예요.",
)


def _clean(value: str) -> str:
    text = str(value or "").strip()
    while len(text) >= 2 and text[0] in "\"'“”‘’" and text[-1] in "\"'“”‘’":
        text = text[1:-1].strip()
    return text


def _split_sentences(text: str) -> list[str]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[\.?!？])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def sister_lines(key: str) -> tuple[str, str, str]:
    """Threads용 3언니 한 줄. 숏폼 내레이션에는 넣지 않는다."""
    index = sum(ord(ch) for ch in key) % 3
    return _REAL[index], _EMPATHY[index], _RAGE[(index + 1) % 3]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load_w_topics() -> tuple[dict, ...]:
    topics = []
    for record in _read_csv(W_CSV):
        title = ensure_curiosity(_clean(record.get("제목안", "")))
        hook = _clean(record.get("훅", ""))
        lines = _split_sentences(hook) + _split_sentences(record.get("전개", ""))
        lines += _split_sentences(record.get("사이다 반전", ""))
        lines = [finish_sentence(line) for line in lines]
        question = _clean(record.get("마지막 질문", "")) or DEFAULT_QUESTION
        real, empathy, rage = sister_lines(record.get("ID", "") or title)
        topics.append(
            {
                "id": (record.get("ID") or "").strip(),
                "title": title,
                "hook": hook,
                "story_lines": lines,
                "question": question,
                "real": real,
                "empathy": empathy,
                "rage": rage,
            }
        )
    return tuple(topics)


@lru_cache(maxsize=1)
def load_adaptations() -> tuple[dict, ...]:
    items = []
    for record in _read_csv(ADAPTED_CSV):
        ep = ep_to_int(record.get("시트 EP", ""))
        if ep is None:
            continue
        title = ensure_curiosity(_clean(record.get("새 제목안", "")))
        twist = _clean(record.get("반전", ""))
        question = _clean(record.get("질문", "")) or DEFAULT_QUESTION
        real, empathy, rage = sister_lines(f"ep{ep}")
        items.append(
            {
                "ep": ep,
                "source_title": _clean(record.get("원제", "")),
                "title": title,
                "hook": title,
                "twist": twist,
                "question": question,
                "real": real,
                "empathy": empathy,
                "rage": rage,
            }
        )
    return tuple(items)


@lru_cache(maxsize=1)
def catalog_title_keys() -> frozenset[str]:
    """새로 넣은 원작 제목. 시트에서 이 제목은 기존 백로그보다 먼저 고른다."""
    keys = {normalize_title(topic["title"]) for topic in load_w_topics()}
    keys.discard("")
    return frozenset(keys)


@lru_cache(maxsize=1)
def adaptation_index() -> tuple[dict[int, dict], dict[str, dict]]:
    by_ep: dict[int, dict] = {}
    by_title: dict[str, dict] = {}
    for item in load_adaptations():
        by_ep[item["ep"]] = item
        source = normalize_title(item["source_title"])
        if source:
            by_title[source] = item
    return by_ep, by_title


def topics_to_append(
    existing_titles: set[str],
    existing_eps: set[int],
    next_ep: int,
) -> list[dict]:
    """시트에 없을 때만 붙일 행. 기존 EP의 각색안은 생성 때 쓰므로 추가하지 않는다."""
    seen = {title for title in existing_titles if title}
    selected: list[dict] = []
    for topic in load_w_topics():
        key = normalize_title(topic["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(dict(topic))
    for item in load_adaptations():
        if item["ep"] in existing_eps:
            continue
        key = normalize_title(item["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        story_lines = _split_sentences(item["hook"]) + _split_sentences(item["twist"])
        story_lines = [finish_sentence(line) for line in story_lines]
        selected.append(
            {
                "id": f"A{item['ep']}",
                "title": item["title"],
                "hook": item["hook"],
                "story_lines": story_lines or [item["twist"]],
                "question": item["question"],
                "real": item["real"],
                "empathy": item["empathy"],
                "rage": item["rage"],
            }
        )
    rows = []
    for offset, topic in enumerate(selected):
        row = dict(topic)
        row["ep"] = f"{next_ep + offset:03d}"
        rows.append(row)
    return rows
