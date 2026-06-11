"""Short-lived one-time tokens for browser EventSource authentication."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class SseTokenRecord:
    endpoint: str
    job_id: str
    scope: str
    expires_at: float


class SseTokenStore:
    """In-memory token store scoped to the current API process."""

    def __init__(self) -> None:
        self._tokens: dict[str, SseTokenRecord] = {}
        self._lock = threading.Lock()

    def create(self, *, endpoint: str, job_id: str, scope: str, ttl_seconds: int) -> tuple[str, str]:
        ttl = max(1, int(ttl_seconds))
        expires_at = time.time() + ttl
        token = secrets.token_urlsafe(32)
        record = SseTokenRecord(endpoint=endpoint, job_id=job_id, scope=scope, expires_at=expires_at)
        with self._lock:
            self._cleanup_locked(time.time())
            self._tokens[token] = record
        return token, datetime.fromtimestamp(expires_at, UTC).isoformat()

    def consume(self, token: str | None, *, endpoint: str, job_id: str, scope: str) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            record = self._tokens.pop(token, None)
        if record is None or record.expires_at < now:
            return False
        return record.endpoint == endpoint and record.job_id == job_id and record.scope == scope

    def _cleanup_locked(self, now: float) -> None:
        expired = [token for token, record in self._tokens.items() if record.expires_at < now]
        for token in expired:
            self._tokens.pop(token, None)


sse_token_store = SseTokenStore()
