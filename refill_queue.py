"""waitmybabe Shorts 스펙 재고 자동 보충 (EP.67 디자인).

멈춘 원인: generate_more_stories.py 는 시트 '행'만 보충하는데, make_shorts.py 는 행마다
손으로 쓴 sayeon_specs/*.json 이 있어야 렌더한다. 스펙을 만드는 단계가 없어서
EP.74(10/5) 이후 '스펙 없음'으로 매일 건너뜀.

이 스크립트는 매 실행마다 make_shorts.py 와 같은 순서(pick_youtube_pending_row)로
YouTube=대기 행을 줄 세우고, 앞쪽 MIN_READY(기본 7)편 중 스펙이 없는 행에 대해
같은 출처(topics/w01_w21.csv 카탈로그 원작 → 없으면 시트 '사연' 열)로 EP.67 스펙을
OpenAI로 써서 sayeon_specs/ 에 저장한다. 대기 행 자체가 MIN_READY 미만이면
generate_more_stories.py 로 시트 행을 먼저 보충한다(시트 자격증명이 있을 때만).

사용:
  python refill_queue.py                 # 시트(GOOGLE_SHEETS_CREDENTIALS)
  python refill_queue.py --xlsx sheet.xlsx --dry-run   # 로컬 시트 사본, 저장 안 함
환경변수: OPENAI_API_KEY (없으면 OPENAI_API_KEY_FIXED), OPENAI_MODEL(기본 gpt-4.1)
"""
from __future__ import annotations

import argparse, copy, csv, glob, json, os, re, sys

from fetch_script import PENDING_STATUS, effective_youtube_status, ep_to_int, pick_youtube_pending_row
from sayeon_render import (
    ESTIMATE_RANGE,
    SPECS_DIR,
    estimate_duration,
    find_spec_for_title,
    segment_spoken,
    spoken_char_count,
    validate_spec,
)
from story_format import normalize_title

ROOT = os.path.dirname(os.path.abspath(__file__))
MIN_READY = int(os.environ.get("REFILL_MIN_READY", "7"))
# 글자 수는 거친 하한. 실제 창은 estimate_duration 의 49~53초(렌더 45~58초보다 좁다).
# EP.79(244자, 42.9초)처럼 짧은 마디가 통과하지 않게 한다.
CHARS = (265, 330)
BANNED = ("진성", "로빈", "대전")
MODEL = os.environ.get("OPENAI_SPEC_MODEL", "gpt-4.1")


def ordered_pending(records: list[dict]) -> list[tuple[int, dict]]:
    """make_shorts 가 고를 순서 그대로 대기 행을 나열한다."""
    recs = [dict(r) for r in records]
    out = []
    while True:
        idx, row = pick_youtube_pending_row(recs)
        if idx is None:
            return out
        out.append((idx, row))
        recs[idx - 2] = dict(recs[idx - 2], YouTube="예약")  # 다음 후보로


def load_records(xlsx: str | None) -> list[dict]:
    if xlsx:
        import openpyxl
        rows = list(openpyxl.load_workbook(xlsx).active.iter_rows(values_only=True))
        hdr = [str(h) for h in rows[0]]
        recs = []
        for r in rows[1:]:
            d = {h: ("" if v is None else (int(v) if isinstance(v, float) and v.is_integer() else v)) for h, v in zip(hdr, r)}
            recs.append(d)
        return recs
    from fetch_script import load_worksheet
    return load_worksheet().get_all_records()


def catalog() -> dict:
    out = {}
    with open(os.path.join(ROOT, "topics", "w01_w21.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[normalize_title(r["제목안"])] = r
    return out


def spoken_chars(spec):
    return spoken_char_count(spec)


def next_episode() -> int:
    eps = [json.load(open(p, encoding="utf-8")).get("episode", 0) for p in glob.glob(os.path.join(SPECS_DIR, "*.json"))]
    return max(eps + [74]) + 1


def check(spec: dict) -> list[str]:
    errs = []
    try:
        validate_spec(spec)
    except ValueError as e:
        errs.append(str(e))
    n = spoken_chars(spec)
    if not CHARS[0] <= n <= CHARS[1]:
        errs.append(f"읽는 글자 수 {n}자 (목표 {CHARS[0]}~{CHARS[1]}자)")
    est = estimate_duration(spec)
    lo, hi = ESTIMATE_RANGE
    if not (lo <= est <= hi):
        hint = "narr/chat spoken 을 한 문장씩 더 길게 쓰세요." if est < lo else "narr/chat spoken 을 줄이세요."
        errs.append(
            f"예상 길이 {est:.1f}s (목표 {lo:.0f}~{hi:.0f}s, 렌더 허용 45~58s). 현재 {n}자. {hint}"
        )
    blob = json.dumps(spec, ensure_ascii=False)
    for b in BANNED:
        if b in blob:
            errs.append(f"금지어 '{b}' 포함")
    for g in spec["segments"]:
        if g.get("voice", "me") not in ("me", "mil", "husband", "fil", "man2"):
            errs.append(f"알 수 없는 voice {g.get('voice')}")
    return errs


SYSTEM = """당신은 유튜브 쇼츠 채널 waitmybabe 의 사연 작가입니다. 여성 1인칭 사이다 반전 사연을
EP.67 디자인 JSON 스펙으로 씁니다. 예시 스펙 두 개와 구조·말투·길이를 똑같이 맞추세요.
규칙:
- segments 는 11~12개: hook → narr/chat 섞어 4~5개 → key(전환 "그래서 저는…") → narr/chat 2~3개 → key(결말, sub 가능) → question.
- chat 은 최소 2개. who/avatar/voice/group 필수. voice 는 me(주인공), mil(시어머니·엄마 세대 여성, 시누이·형님·동서도 가능), husband(남편·남자친구·시동생), fil(시아버지·어른 남성), man2(업체·제3자 남성) 중 하나.
- hook/key/question 의 text 는 \\n 으로 3줄, **강조** 1곳. size 70~76. spoken 은 숫자·이모지 없이 한글로.
- 숫자·영어·이모지가 들어간 narr/chat 은 spoken 에 한글로 풀어 쓰기.
- 전체 읽는 분량(spoken 기준, 공백 제외) 280~310자. narr 와 chat 의 spoken 은 각각 24자 이상.
  짧은 마디를 여러 개 두지 말고, 상황·증거·반응이 한 문장에 들어가게 쓰세요. 예상 낭독은 49~53초입니다.
  길이 수정을 요청받으면 장면을 새로 쓰지 말고, spoken 만 요청한 글자 수만큼 조절하세요. 한 번에 40자 넘게 늘리거나 줄이지 마세요.
- 실명·지명·회사명 금지. 특히 '진성', '로빈', '대전' 은 절대 쓰지 마세요.
- title 은 반드시 주어진 topic 그대로 + " #Shorts" (topic 에 ", 결말은?" 이 없으면 붙이지 말 것).
- description 은 예시와 같은 형식(2줄 요약 / 질문+댓글로 알려주세요 👇 / "매일 저녁, 속이 뻥 뚫리는 사이다 사연이 올라옵니다." / 창작·각색·AI 음성 표기 / 해시태그 7개 #Shorts 로 끝).
- tags 12개 내외, "사연","사이다사연","사이다" 로 시작, "shorts","쇼츠" 로 끝.
- disclosure 는 "※ 본 사연은 창작·각색된 이야기이며, AI 음성으로 제작되었습니다."
JSON 객체 하나만 출력."""


# 로컬 보정으로 메울 수 있는 최대 차이. 그보다 크면 모델이 다시 쓴다.
_MAX_SEC_GAP = 8.0
_MAX_CHAR_GAP = 70
_MAX_ADJUST_STEPS = 8
# 공백 제외 글자 수가 짧은 순. 너무 긴 덧붙임은 53초를 넘기므로 짧은 것부터 시도한다.
_PADS = (
    "그날도 같았어요.",
    "그 말이 남았어요.",
    "그 말이 오래 남았어요.",
    "그날 일이 쉽게 잊히지 않았어요.",
    "그 한마디가 한참 동안 마음에 남았어요.",
)


def _plain_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _is_length_error(err: str) -> bool:
    return err.startswith("읽는 글자 수") or err.startswith("예상 길이")


def _gap(spec: dict) -> tuple[int, float, bool, bool]:
    n = spoken_chars(spec)
    est = estimate_duration(spec)
    long = est > ESTIMATE_RANGE[1] or n > CHARS[1]
    short = est < ESTIMATE_RANGE[0] or n < CHARS[0]
    return n, est, long, short


def _length_side(chars: int, seconds: float) -> int:
    if seconds > ESTIMATE_RANGE[1] or chars > CHARS[1]:
        return 1
    if seconds < ESTIMATE_RANGE[0] or chars < CHARS[0]:
        return -1
    return 0


def _capture_segment(seg: dict) -> tuple[bool, str | None, str | None]:
    return ("spoken" in seg, seg.get("spoken"), seg.get("text"))


def _restore_segment(seg: dict, saved: tuple[bool, str | None, str | None]) -> None:
    had_spoken, spoken, text = saved
    if had_spoken:
        seg["spoken"] = spoken
    else:
        seg.pop("spoken", None)
    if text is None:
        seg.pop("text", None)
    else:
        seg["text"] = text


def _apply_spoken(seg: dict, new_spoken: str) -> None:
    """spoken 을 바꾼다. 화면 글과 낭독이 같았으면 화면 글도 같이 맞춘다."""
    old = segment_spoken(seg)
    text = str(seg.get("text") or "")
    plain = re.sub(r"\s+", " ", text.replace("**", "").replace("\n", " ")).strip()
    old_norm = re.sub(r"\s+", " ", old).strip()
    seg["spoken"] = new_spoken
    if plain == old_norm and "\n" not in text and "**" not in text:
        seg["text"] = new_spoken


def _trim_text(spoken: str) -> str | None:
    """마지막 문장이나 쉼표 절을 하나 뺀다. 너무 짧아지면 None."""
    spoken = spoken.strip()
    sents = [s.strip() for s in re.findall(r"[^.!?…]+[.!?…]+", spoken) if s.strip()]
    if len(sents) >= 2 and _plain_chars(sents[-1]) >= 6 and _plain_chars("".join(sents[:-1])) >= 12:
        return " ".join(sents[:-1]).strip()
    head = re.sub(r"[,，]\s*[^,，]+$", "", spoken).strip()
    if head and head != spoken and _plain_chars(head) >= 12 and _plain_chars(spoken) - _plain_chars(head) >= 8:
        if head[-1:] not in ".?!…":
            head += "."
        return head
    return None


def _narr_or_chat(spec: dict) -> list[dict]:
    narr = [g for g in spec.get("segments") or [] if g.get("type") == "narr"]
    chat = [g for g in spec.get("segments") or [] if g.get("type") == "chat"]
    return narr + chat


def _trim_once(spec: dict) -> bool:
    segs = sorted(_narr_or_chat(spec), key=lambda g: _plain_chars(segment_spoken(g)), reverse=True)
    for seg in segs:
        new = _trim_text(segment_spoken(seg))
        if not new:
            continue
        saved = _capture_segment(seg)
        _apply_spoken(seg, new)
        _n, _est, long, short = _gap(spec)
        if short and not long:
            _restore_segment(seg, saved)
            continue
        return True
    return False


def _pad_once(spec: dict) -> bool:
    segs = [g for g in spec.get("segments") or [] if g.get("type") == "narr"]
    if not segs:
        segs = [g for g in spec.get("segments") or [] if g.get("type") == "chat"]
    if not segs:
        return False
    fresh = [g for g in segs if not any(segment_spoken(g).rstrip().endswith(pad) for pad in _PADS)]
    pool = fresh or segs
    seg = max(pool, key=lambda g: _plain_chars(segment_spoken(g)))
    base = segment_spoken(seg).rstrip()
    saved = _capture_segment(seg)
    progressed = None
    for pad in sorted(_PADS, key=_plain_chars):
        _apply_spoken(seg, f"{base} {pad}".strip())
        _n, _est, long, short = _gap(spec)
        if not long and not short:
            return True
        if short and not long:
            progressed = _capture_segment(seg)
            continue
        break
    if progressed is not None:
        _restore_segment(seg, progressed)
        return True
    _restore_segment(seg, saved)
    return False


def adjust_spec_to_window(spec: dict) -> dict | None:
    """길이만 조금 벗어난 스펙을 narr/chat spoken 보정으로 49~53초에 맞춘다.

    구조 오류가 있거나 차이가 크면 None. 인자로 받은 스펙은 바꾸지 않는다.
    """
    spec = copy.deepcopy(spec)
    errs = check(spec)
    if not errs:
        return spec
    if any(not _is_length_error(e) for e in errs):
        return None
    n, est, long, short = _gap(spec)
    if long and short:
        return None
    if est < ESTIMATE_RANGE[0] - _MAX_SEC_GAP or est > ESTIMATE_RANGE[1] + _MAX_SEC_GAP:
        return None
    if n < CHARS[0] - _MAX_CHAR_GAP or n > CHARS[1] + _MAX_CHAR_GAP:
        return None
    for _ in range(_MAX_ADJUST_STEPS):
        if not check(spec):
            return spec
        _n, _est, long, short = _gap(spec)
        if long and short:
            return None
        if long:
            if not _trim_once(spec):
                return None
        elif short:
            if not _pad_once(spec):
                return None
        else:
            return spec
    return spec if not check(spec) else None


def length_retry_message(history: list[tuple[int, float]], errs: list[str]) -> str:
    """재생성 프롬프트. 직전과 이번이 창의 반대쪽이면 중간 글자 수를 지정한다."""
    n, est = history[-1]
    parts = [
        "다음을 고쳐 JSON 전체를 다시 주세요.",
        "플롯과 세그먼트 수는 유지하고 narr/chat 의 spoken 만 조정하세요.",
        "; ".join(errs),
    ]
    if any(_is_length_error(e) for e in errs):
        target_n = (CHARS[0] + CHARS[1]) // 2
        target_s = (ESTIMATE_RANGE[0] + ESTIMATE_RANGE[1]) / 2
        if len(history) >= 2:
            prev_n, prev_est = history[-2]
            if _length_side(prev_n, prev_est) * _length_side(n, est) < 0:
                target_n = (prev_n + n) // 2
                parts.append(
                    f"직전 {prev_n}자/{prev_est:.1f}초와 이번 {n}자/{est:.1f}초가 반대쪽입니다. "
                    f"장면을 새로 쓰지 말고 그 중간인 약 {target_n}자에 맞추세요."
                )
        delta = target_n - n
        verb = "늘려" if delta >= 0 else "줄여"
        parts.append(
            f"목표 약 {target_n}자, {target_s:.0f}초. 지금은 {n}자, {est:.1f}초이니 약 {abs(delta)}자만 {verb} 주세요."
        )
    return " ".join(parts)


def write_spec(client, row: dict, cat: dict | None, ep: int, refs: list[dict]) -> dict:
    title = str(row.get("제목", "")).strip()
    if cat:
        src = f"훅: {cat['훅']}\n전개: {cat['전개']}\n사이다 반전: {cat['사이다 반전']}\n마지막 질문: {cat['마지막 질문']}"
    else:
        src = f"사연 원문(시트):\n{row.get('사연','')}\n질문: {row.get('질문','')}\n(원문이 밋밋하면 증거·제3자로 되갚는 사이다 결말을 새로 만드세요.)"
    user = (f"예시1:\n{json.dumps(refs[0], ensure_ascii=False)}\n\n예시2:\n{json.dumps(refs[1], ensure_ascii=False)}\n\n"
            f"이번 편: episode={ep}, label=\"오늘의 사연 · EP.{ep}\", topic=\"{title}\".\n"
            f"slug 는 \"waitmybabe_EP{ep}_<핵심 단어 2~5글자>\".\n{src}")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    last = []
    history: list[tuple[int, float]] = []
    for attempt in range(6):
        temperature = 0.7 if attempt == 0 else 0.2
        r = client.chat.completions.create(
            model=MODEL, temperature=temperature, response_format={"type": "json_object"}, messages=msgs
        )
        raw = r.choices[0].message.content
        spec = json.loads(raw)
        spec.update(channel="sayeon", episode=ep, topic=title, label=f"오늘의 사연 · EP.{ep}")
        spec["slug"] = re.sub(r"[^\w가-힣_]", "", spec.get("slug") or f"waitmybabe_EP{ep}")
        if not spec["slug"].startswith(f"waitmybabe_EP{ep}"):
            spec["slug"] = f"waitmybabe_EP{ep}"
        last = check(spec)
        if not last:
            return spec
        fitted = adjust_spec_to_window(spec)
        if fitted is not None and not check(fitted):
            print(f"    길이 보정: {spoken_chars(fitted)}자, 예상 {estimate_duration(fitted):.1f}s")
            return fitted
        history.append((spoken_chars(spec), estimate_duration(spec)))
        print(f"    재시도 {attempt+1}: {last}")
        msgs += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": length_retry_message(history, last)},
        ]
    raise RuntimeError(f"{title}: 스펙 검증 실패 {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", help="시트 xlsx 사본(로컬 테스트)")
    ap.add_argument("--min", type=int, default=MIN_READY)
    ap.add_argument("--dry-run", action="store_true", help="부족분만 보고하고 생성하지 않음")
    a = ap.parse_args()

    records = load_records(a.xlsx)
    queue = ordered_pending(records)
    if len(queue) < a.min and not a.xlsx and os.environ.get("GOOGLE_SHEETS_CREDENTIALS"):
        print(f"대기 행 {len(queue)}개 < {a.min}: generate_more_stories.py 로 시트 행 보충")
        import subprocess
        subprocess.run([sys.executable, os.path.join(ROOT, "generate_more_stories.py")], check=False)
        records = load_records(None); queue = ordered_pending(records)

    head = queue[: a.min]
    missing = [(i, r) for i, r in head if find_spec_for_title(str(r.get("제목", "")))[0] is None]
    ready = len(head) - len(missing)
    print(f"대기 {len(queue)}행, 다음 {len(head)}편 중 스펙 준비 {ready}편, 부족 {len(missing)}편")
    for i, r in head:
        p, _ = find_spec_for_title(str(r.get("제목", "")))
        print(f"  행{i} EP{r.get('EP')} {r.get('제목')} -> {os.path.basename(p) if p else '(스펙 없음)'}")
    if not missing or a.dry_run:
        return 0

    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY_FIXED") or os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY 가 없어 보충하지 못했습니다."); return 1
    client = OpenAI(api_key=key)
    refs = [json.load(open(os.path.join(SPECS_DIR, "reference", f), encoding="utf-8")) for f in ("sayeon_ep067.json", "sayeon_ep068.json")]
    cats = catalog()
    # 방송 회차 = 68 + (분홍판으로 올라간 행 수) + 큐 위치. CI에서 스펙 푸시가 안 돼도 번호가 겹치지 않게.
    done = sum(1 for x in records if effective_youtube_status(x) != PENDING_STATUS and (ep_to_int(x.get("EP")) or 0) >= 70)
    last_used = 68 + done
    pos = {i: k for k, (i, _) in enumerate(queue)}
    fails = 0
    for i, r in missing:
        ep = max(last_used + pos[i] + 1, 75)
        title = str(r.get("제목", ""))
        print(f"[refill] EP.{ep} ← 행{i} {title}")
        try:
            spec = write_spec(client, r, cats.get(normalize_title(title)), ep, refs)
        except Exception as e:  # 한 편 실패해도 나머지는 계속
            print(f"  실패: {e}"); fails += 1; continue
        path = os.path.join(SPECS_DIR, f"sayeon_ep{ep:03d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2); f.write("\n")
        print(f"  저장 {path} ({spoken_chars(spec)}자)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
