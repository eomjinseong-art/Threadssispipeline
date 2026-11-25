"""쿠팡 파트너스 고지 + 링크 (2026-11-25 승인).

새로 올리는 waitmybabe Short 설명란 첫 줄 = 고지 문구, 둘째 줄 = 쿠팡 링크.
같은 내용을 댓글 맨 앞에도 넣는다(상단 고정은 API 미지원 → Studio에서 직접).
주제별 파트너스 링크가 레포에 없어 기존 기본 링크를 쓴다. 링크를 새로 만들지 않는다.
"""

COUPANG_NOTICE = "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
DEFAULT_PARTNER_LINK = "https://link.coupang.com/a/hsdzLh1vB6"
# 주제별 링크가 생기면 여기에 키를 추가한다. 없으면 기본 링크.
TOPIC_PARTNER_LINKS = {}
PARTNER_LINK = DEFAULT_PARTNER_LINK
LINK_LINE = "🛒 추천 링크: " + PARTNER_LINK


def partner_link(topic: str | None = None) -> str:
    key = (topic or "").strip()
    return TOPIC_PARTNER_LINKS.get(key, DEFAULT_PARTNER_LINK)


def disclosure_block() -> str:
    return COUPANG_NOTICE + "\n" + LINK_LINE


def with_disclosure(description: str) -> str:
    body = (description or "").strip()
    if body.startswith(COUPANG_NOTICE):
        return body
    return disclosure_block() + ("\n\n" + body if body else "")


def comment_text(extra: str = "") -> str:
    extra = (extra or "").strip()
    if extra.startswith(COUPANG_NOTICE):
        return extra
    return disclosure_block() + ("\n\n" + extra if extra else "")
