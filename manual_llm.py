"""Optional manual LLM client.

Scheduled workflows must not call this. They consume ``content_queue/queue.json``.
When a person runs ``generate_more_stories.py`` or ``refill_queue.py`` by hand,
Gemini (OpenAI-compatible endpoint) is preferred over OpenAI.
"""

from __future__ import annotations

import os

GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

SCHEDULED_LLM_LOG = (
    "[llm] 스케줄 워크플로에서는 LLM을 호출하지 않습니다. "
    "커밋된 content queue를 사용하세요."
)


class ScheduledLlmBlocked(RuntimeError):
    """Raised when a manual generation entrypoint is invoked on GitHub Actions."""


def scheduled_llm_blocked() -> bool:
    """True on Actions unless a person explicitly opts in for a one-off manual run."""
    if os.environ.get("ALLOW_MANUAL_LLM") == "1":
        return False
    return os.environ.get("GITHUB_ACTIONS") == "true"


def open_manual_client(default_openai_model: str, *, openai_model_env: str):
    """Return ``(client, model)`` for a manual script.

    Preference order: ``GEMINI_API_KEY`` (``gemini-2.5-flash``), then
    ``OPENAI_API_KEY_FIXED`` / ``OPENAI_API_KEY``. Never called by the
    scheduled workflows.
    """
    if scheduled_llm_blocked():
        raise ScheduledLlmBlocked(SCHEDULED_LLM_LOG)
    gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    openai_key = (
        os.environ.get("OPENAI_API_KEY_FIXED") or os.environ.get("OPENAI_API_KEY") or ""
    ).strip()
    from openai import OpenAI

    if gemini_key:
        model = (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
        return OpenAI(api_key=gemini_key, base_url=GEMINI_OPENAI_BASE), model
    if openai_key:
        model = (os.environ.get(openai_model_env) or default_openai_model).strip()
        return OpenAI(api_key=openai_key), model
    raise SystemExit(
        "수동 생성에는 GEMINI_API_KEY(우선) 또는 OPENAI_API_KEY 가 필요합니다."
    )
