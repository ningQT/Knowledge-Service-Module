"""Request-scoped logging context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4

_LOG_ID: ContextVar[str | None] = ContextVar("ksm_log_id", default=None)
_LLM_COUNTER: ContextVar[int] = ContextVar("ksm_llm_counter", default=0)


def new_log_id() -> str:
    """Return a short, URL/header-safe request log identifier."""
    return f"log_{uuid4().hex[:16]}"


def get_log_id() -> str:
    return _LOG_ID.get() or "-"


def set_log_id(log_id: str) -> Token[str | None]:
    reset_llm_counter()
    return _LOG_ID.set(log_id)


def reset_log_id(token: Token[str | None]) -> None:
    _LOG_ID.reset(token)


def reset_llm_counter() -> None:
    _LLM_COUNTER.set(0)


def next_llm_call_id() -> str:
    next_value = _LLM_COUNTER.get() + 1
    _LLM_COUNTER.set(next_value)
    return f"llm_{next_value:04d}_{uuid4().hex[:8]}"
