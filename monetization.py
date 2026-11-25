"""쿠팡 파트너스 고지 + 링크 (2026-11-25 승인).

새로 올리는 waitmybabe Short 설명란 첫 줄 = 고지 문구, 둘째 줄 = 링크.
같은 내용을 댓글 맨 앞에도 넣는다(상단 고정은 API 미지원 → Studio에서 직접).
링크는 실제로 쓰고 있는 티나링크엄 허브 + UTM. 차 리스·DB 수집형 CPA 링크는 넣지 않는다.
"""

COUPANG_NOTICE = "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
UTM_CAMPAIGN = "waitmybabe"
PARTNER_LINK = (
    "https://tinalinkeom.vercel.app/"
    f"?utm_source=youtube&utm_medium=shorts&utm_campaign={UTM_CAMPAIGN}"
)
LINK_LINE = "🛒 추천 링크 모음: " + PARTNER_LINK


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
