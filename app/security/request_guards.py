"""Request-level security guards for browser writes and lightweight throttling."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

from fastapi import Request

from app.api.dependencies import AUTH_COOKIE_NAME
from app.config import Settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def request_scheme(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
        if forwarded in {"http", "https"}:
            return forwarded
    return request.url.scheme


def should_use_secure_cookie(request: Request, settings: Settings) -> bool:
    env = os.getenv("KSM_ENV", "").strip().lower()
    production_env = env in {"prod", "production"}
    return bool(settings.secure_cookies or production_env or request_scheme(request, settings) == "https")


def csrf_origin_allowed(request: Request, settings: Settings) -> bool:
    if not settings.enable_csrf_protection:
        return True
    if request.method.upper() in SAFE_METHODS:
        return True
    if not str(request.url.path).startswith("/api/"):
        return True
    if not request.cookies.get(AUTH_COOKIE_NAME):
        return True

    trusted = _trusted_origins(settings)
    origin = _origin_from_header(request.headers.get("origin"))
    if origin:
        return origin in trusted

    referer = _origin_from_header(request.headers.get("referer"))
    return bool(referer and referer in trusted)


def _trusted_origins(settings: Settings) -> set[str]:
    raw = settings.csrf_trusted_origins or settings.cors_origins
    return {
        _origin_from_header(item) or item.strip().rstrip("/")
        for item in str(raw or "").split(",")
        if item.strip()
    }


def _origin_from_header(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass
class InMemoryRateLimiter:
    """Small fixed-window limiter scoped to a FastAPI app process."""

    settings: Settings
    _hits: dict[tuple[str, str, int], int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, request: Request) -> bool:
        if not self.settings.rate_limit_enabled:
            return True
        group, limit = _rate_group(request, self.settings)
        if limit <= 0:
            return True
        window = max(1, int(self.settings.rate_limit_window_seconds))
        now_window = int(time.time() // window)
        key = (_client_key(request, self.settings), group, now_window)
        with self._lock:
            self._cleanup(now_window)
            count = self._hits.get(key, 0) + 1
            self._hits[key] = count
            return count <= limit

    def _cleanup(self, current_window: int) -> None:
        stale = [key for key in self._hits if key[2] < current_window - 1]
        for key in stale:
            self._hits.pop(key, None)


def _rate_group(request: Request, settings: Settings) -> tuple[str, int]:
    path = str(request.url.path)
    method = request.method.upper()
    if path.startswith("/api/v1/auth/"):
        return "auth", settings.rate_limit_auth_per_window
    if _is_heavy_path(path):
        return "heavy", settings.rate_limit_heavy_per_window
    if path.startswith("/api/") and method not in SAFE_METHODS:
        return "write", settings.rate_limit_write_per_window
    return "default", settings.rate_limit_default_per_window


def _is_heavy_path(path: str) -> bool:
    # SSE endpoints are long-lived connections, not heavy operations
    if path.endswith("/sse"):
        return False
    return (
        (
            path.startswith("/api/v1/instances/")
            and (
                path.endswith("/ingest")
                or "/ingest/" in path
            )
        )
        or path.startswith("/api/v1/search")
        or path.startswith("/api/v1/settings/llm/test")
    )


def _client_key(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"
