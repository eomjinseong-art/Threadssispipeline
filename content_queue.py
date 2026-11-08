"""Committed story/spec queue consumed by scheduled workflows.

The daily jobs copy items from ``content_queue/queue.json`` onto the Google
Sheet. They do not call an LLM. ``content_queue/state.json`` records which
ids have already been handed to the sheet (or were already there).

Posting rates used for runway:
  Threads — 3 posts/day (``.github/workflows/daily_threads.yml``)
  Shorts  — 1 post/day  (``.github/workflows/daily_shorts.yml``)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fetch_script import PENDING_STATUS, effective_youtube_status, ep_to_int
from story_format import ensure_curiosity, normalize_title, strip_leading_ep
from topic_catalog import sister_lines

ROOT = Path(__file__).resolve().parent
QUEUE_PATH = ROOT / "content_queue" / "queue.json"
STATE_PATH = ROOT / "content_queue" / "state.json"
SPECS_DIR = ROOT / "sayeon_specs"

THREADS_PER_DAY = 3
SHORTS_PER_DAY = 1
MIN_PENDING = 10
QUEUE_VERSION = 1

EMPTY_LOG = "[content-queue] 큐가 비어 있어 이번 보충을 건너뜁니다."
STOCKED_LOG = "[content-queue] 재고가 충분해 큐를 소비하지 않고 건너뜁니다."
NO_CREDS_LOG = "[content-queue] 시트 자격증명이 없어 큐를 소비하지 않고 건너뜁니다."

REQUIRED_FIELDS = ("id", "title", "story_lines", "real", "empathy", "rage", "question", "spec")
_WS = re.compile(r"\s+")


def title_key(title: str) -> str:
    """Same identity the sheet and the spec matcher use for a story title."""
    return normalize_title(ensure_curiosity(str(title or "")))


def clean_spoken(segment: dict) -> str:
    raw = segment.get("spoken") or segment.get("text") or ""
    return _WS.sub(" ", str(raw).replace("**", "").replace("\n", " ")).strip()


def story_lines_from_spec(spec: dict) -> list[str]:
    """Narration the Threads body can post: hook, narr, and key cards."""
    lines: list[str] = []
    for segment in spec.get("segments") or []:
        if segment.get("type") not in {"hook", "narr", "key"}:
            continue
        line = clean_spoken(segment)
        if line:
            lines.append(line)
    return lines


def question_from_spec(spec: dict) -> str:
    for segment in spec.get("segments") or []:
        if segment.get("type") == "question":
            line = clean_spoken(segment)
            if line:
                return line
    return "여러분이라면 어떻게 하셨을까요?"


def item_from_spec(path: Path, spec: dict | None = None) -> dict:
    """Build one queue item from an on-disk EP.67 spec. Does not write the file."""
    if spec is None:
        spec = json.loads(path.read_text(encoding="utf-8"))
    episode = int(spec.get("episode") or 0)
    title = str(spec.get("topic") or "").strip()
    if not title or episode <= 0:
        raise ValueError(f"{path} 에 topic 또는 episode 가 없습니다.")
    real, empathy, rage = sister_lines(title)
    rel = path.relative_to(ROOT).as_posix() if path.is_absolute() else Path(path).as_posix()
    return {
        "id": f"ep{episode:03d}",
        "title": title,
        "story_lines": story_lines_from_spec(spec),
        "real": real,
        "empathy": empathy,
        "rage": rage,
        "question": question_from_spec(spec),
        "spec": rel,
    }


def load_queue(path: Path | None = None) -> list[dict]:
    path = path or QUEUE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != QUEUE_VERSION:
        raise ValueError(f"{path} version 은 {QUEUE_VERSION} 이어야 합니다.")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{path} 의 items 는 배열이어야 합니다.")
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{index}번째 항목이 객체가 아닙니다.")
        missing = [key for key in REQUIRED_FIELDS if not item.get(key)]
        if missing:
            raise ValueError(f"{item.get('id') or index}번째 항목에 빈 필드: {missing}")
        if not isinstance(item["story_lines"], list) or not all(str(line).strip() for line in item["story_lines"]):
            raise ValueError(f"{item['id']} story_lines 가 비어 있습니다.")
        if item["id"] in seen:
            raise ValueError(f"중복 id {item['id']}")
        seen.add(item["id"])
    return items


def empty_state() -> dict:
    return {"consumed_ids": []}


def load_state(path: Path | None = None) -> dict:
    path = path or STATE_PATH
    if not path.exists():
        return empty_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 는 객체여야 합니다.")
    ids = data.get("consumed_ids") or []
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ValueError(f"{path} consumed_ids 는 문자열 배열이어야 합니다.")
    return {"consumed_ids": sorted(set(ids))}


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"consumed_ids": sorted(set(state.get("consumed_ids") or []))}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _spec_file(item: dict, root: Path) -> Path:
    spec = Path(str(item.get("spec") or ""))
    if spec.is_absolute():
        return spec
    return root / spec


def threads_candidate(item: dict) -> bool:
    return bool(item.get("story_lines")) and bool(str(item.get("title") or "").strip())


def shorts_candidate(item: dict, root: Path | None = None) -> bool:
    return threads_candidate(item) and _spec_file(item, root or ROOT).is_file()


def _unconsumed(items: list[dict], state: dict) -> list[dict]:
    done = set(state.get("consumed_ids") or [])
    return [item for item in items if item.get("id") not in done]


def inventory(items: list[dict], state: dict, root: Path | None = None) -> dict:
    """Runway of the committed queue. Sheet backlog is not included.

    An item counts only when it still has story text and a spec file.
    Threads and Shorts share that set; the day counts differ because
    Threads posts three times a day and Shorts once.
    """
    root = root or ROOT
    pending = [item for item in _unconsumed(items, state) if shorts_candidate(item, root)]
    left = len(pending)
    return {
        "threads_left": left,
        "shorts_left": left,
        "threads_days": left / THREADS_PER_DAY,
        "shorts_days": left / SHORTS_PER_DAY,
        "threads_per_day": THREADS_PER_DAY,
        "shorts_per_day": SHORTS_PER_DAY,
    }


def format_inventory(inv: dict) -> str:
    return (
        f"Threads 남은 항목: {inv['threads_left']} ({inv['threads_days']:.2f}일)"
        f" / Shorts 남은 항목: {inv['shorts_left']} ({inv['shorts_days']:.2f}일)"
    )


def sheet_title_keys(records: list[dict]) -> set[str]:
    keys = set()
    for row in records:
        key = title_key(str(row.get("제목", "")))
        if key:
            keys.add(key)
    return keys


def count_threads_pending(records: list[dict]) -> int:
    return sum(1 for row in records if str(row.get("Status", "")).strip() == PENDING_STATUS)


def count_shorts_pending(records: list[dict], specs_dir: Path | None = None) -> int:
    """YouTube=대기 이면서 EP.67 스펙이 있는 행 수.

    스펙 없는 대기 행은 make_shorts.py 가 올릴 수 없으므로 재고로 세지 않는다.
    (10/29~11/7: 스펙 없는 대기 130행 때문에 큐 보충이 '재고 충분'으로 건너뛰었다.)
    """
    from sayeon_render import load_specs, topic_key

    specs = load_specs(str(specs_dir or SPECS_DIR))
    keys = set()
    for _path, spec in specs:
        for candidate in (spec.get("topic"), spec.get("title")):
            if candidate:
                keys.add(topic_key(candidate))
    return sum(
        1
        for row in records
        if effective_youtube_status(row) == PENDING_STATUS
        and topic_key(str(row.get("제목", ""))) in keys
    )


def next_episode(records: list[dict]) -> int:
    numbers = [ep_to_int(row.get("EP", "")) for row in records]
    present = [number for number in numbers if number is not None]
    return max(present, default=0) + 1


def mark_already_on_sheet(items: list[dict], records: list[dict], state: dict) -> list[str]:
    """Ids whose title is already a sheet row. They are not appended again."""
    keys = sheet_title_keys(records)
    done = set(state.get("consumed_ids") or [])
    newly: list[str] = []
    for item in items:
        if item["id"] in done:
            continue
        if title_key(item["title"]) in keys:
            done.add(item["id"])
            newly.append(item["id"])
    state["consumed_ids"] = sorted(done)
    return newly


def choose_to_append(
    items: list[dict],
    state: dict,
    *,
    threads_pending: int,
    shorts_pending: int,
    root: Path | None = None,
    min_pending: int = MIN_PENDING,
) -> list[dict]:
    """Items to copy onto the sheet so both pending counts can reach ``min_pending``.

    One new row is Status=대기 and (by the EP seed rule) YouTube=대기, so it
    counts for both pipelines. Rows without a spec file are not appended:
    ``make_shorts.py`` stops on the first pending title that has no spec.
    """
    root = root or ROOT
    if threads_pending >= min_pending and shorts_pending >= min_pending:
        return []
    chosen: list[dict] = []
    threads = threads_pending
    shorts = shorts_pending
    for item in _unconsumed(items, state):
        if threads >= min_pending and shorts >= min_pending:
            break
        if not shorts_candidate(item, root):
            continue
        chosen.append(item)
        threads += 1
        shorts += 1
    return chosen


def item_to_row(item: dict, episode: int) -> list[str]:
    title = ensure_curiosity(strip_leading_ep(str(item["title"])))
    return [
        PENDING_STATUS,
        f"{episode:03d}",
        title,
        "\n".join(str(line).strip() for line in item["story_lines"] if str(line).strip()),
        str(item["real"]).strip(),
        str(item["empathy"]).strip(),
        str(item["rage"]).strip(),
        str(item["question"]).strip(),
    ]


def rows_for_items(items: list[dict], start_episode: int) -> list[list[str]]:
    return [item_to_row(item, start_episode + offset) for offset, item in enumerate(items)]


def mark_consumed(state: dict, ids: list[str]) -> None:
    done = set(state.get("consumed_ids") or [])
    done.update(ids)
    state["consumed_ids"] = sorted(done)


def run_consume(
    *,
    queue_path: Path | None = None,
    state_path: Path | None = None,
    sheet_loader=None,
    dry_run: bool = False,
    channel: str = "all",
    root: Path | None = None,
) -> int:
    """Top up the sheet from the committed queue. Returns 0 when the run should continue.

    An empty queue logs ``EMPTY_LOG`` and does not call an LLM.
    """
    root = root or ROOT
    queue_path = queue_path or QUEUE_PATH
    state_path = state_path or STATE_PATH
    label = channel or "all"

    if not queue_path.exists():
        print(f"{EMPTY_LOG} ({label})")
        print("[content-queue] " + format_inventory(inventory([], empty_state(), root)))
        return 0

    try:
        items = load_queue(queue_path)
        state = load_state(state_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[content-queue] 큐를 읽지 못했습니다: {exc}")
        return 1

    inv = inventory(items, state, root)
    if inv["threads_left"] == 0 and inv["shorts_left"] == 0:
        print(f"{EMPTY_LOG} ({label})")
        print("[content-queue] " + format_inventory(inv))
        return 0

    if sheet_loader is None:
        if not os.environ.get("GOOGLE_SHEETS_CREDENTIALS"):
            print(f"{NO_CREDS_LOG} ({label})")
            print("[content-queue] " + format_inventory(inv))
            return 0
        from fetch_script import load_worksheet

        sheet_loader = load_worksheet

    try:
        worksheet = sheet_loader()
        records = worksheet.get_all_records()
    except SystemExit as exc:
        print(f"{NO_CREDS_LOG} ({label}) {exc}")
        print("[content-queue] " + format_inventory(inv))
        return 0
    except Exception as exc:
        print(f"[content-queue] 시트를 읽지 못해 보충을 건너뜁니다: {exc}")
        return 1

    already = mark_already_on_sheet(items, records, state)
    if already:
        print(f"[content-queue] 시트에 이미 있는 제목 {len(already)}개를 소비로 표시합니다.")

    threads_pending = count_threads_pending(records)
    shorts_pending = count_shorts_pending(records)
    chosen = choose_to_append(
        items,
        state,
        threads_pending=threads_pending,
        shorts_pending=shorts_pending,
        root=root,
    )
    inv = inventory(items, state, root)

    if not chosen:
        stocked = threads_pending >= MIN_PENDING and shorts_pending >= MIN_PENDING
        if stocked and (inv["threads_left"] or inv["shorts_left"]):
            print(
                f"{STOCKED_LOG} ({label}, Threads 대기 {threads_pending}개, "
                f"YouTube 대기 {shorts_pending}개)"
            )
        else:
            print(f"{EMPTY_LOG} ({label})")
        print("[content-queue] " + format_inventory(inv))
        if already and not dry_run:
            save_state(state, state_path)
        return 0

    start = next_episode(records)
    rows = rows_for_items(chosen, start)
    print(
        f"[content-queue] {label}: 큐에서 {len(chosen)}개를 시트 EP.{start:03d}부터 보충합니다."
    )
    for item, row in zip(chosen, rows):
        print(f"  {item['id']} → EP.{row[1]} {row[2]} ({item['spec']})")

    if dry_run:
        print("[content-queue] dry-run: 시트와 상태 파일은 바꾸지 않습니다.")
        print("[content-queue] " + format_inventory(inv))
        return 0

    worksheet.append_rows(rows, value_input_option="USER_ENTERED")
    mark_consumed(state, [item["id"] for item in chosen])
    save_state(state, state_path)
    inv = inventory(items, state, root)
    print("[content-queue] " + format_inventory(inv))
    return 0


def commit_state_if_actions(state_path: Path | None = None) -> None:
    """Push ``state.json`` from a scheduled job. A failed push does not fail the run.

    The next run treats titles already on the sheet as consumed, so a missed
    push does not append the same story twice.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    state_path = (state_path or STATE_PATH).resolve()
    if state_path != STATE_PATH.resolve():
        return
    import subprocess

    ref = os.environ.get("GITHUB_REF", "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ""
    if not branch:
        print("[content-queue] 브랜치 체크아웃이 아니라 상태 푸시를 건너뜁니다.")
        return

    def git(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    git(["git", "config", "user.name", "github-actions[bot]"])
    git(["git", "config", "user.email", "41898283+github-actions[bot]@users.noreply.github.com"])
    dirty = git(["git", "status", "--porcelain", "--", "content_queue/state.json"]).stdout.strip()
    if not dirty:
        return
    if git(["git", "add", "--", "content_queue/state.json"]).returncode != 0:
        print("[content-queue] 상태 파일을 커밋하지 못했습니다. 다음 실행이 시트 제목으로 맞춥니다.")
        return
    committed = git(["git", "commit", "-m", "chore: mark consumed content-queue items"])
    if committed.returncode != 0:
        print("[content-queue] 상태 파일을 커밋하지 못했습니다. 다음 실행이 시트 제목으로 맞춥니다.")
        return
    pushed = git(["git", "push", "origin", f"HEAD:{branch}"])
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "push failed"
        print(f"[content-queue] 상태 푸시 실패(권한). 다음 실행이 시트 제목으로 맞춥니다. {tail}")
        return
    print("[content-queue] 소비 상태를 저장소에 푸시했습니다.")
