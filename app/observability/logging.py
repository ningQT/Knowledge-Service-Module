"""Structured key-value logging primitives."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.observability.context import get_log_id

SENSITIVE_FIELD_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)
_RECORD_FACTORY_INSTALLED = False


class RequestLogFilter(logging.Filter):
    """Inject request-scoped fields into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "log_id"):
            record.log_id = get_log_id()
        if not hasattr(record, "event"):
            record.event = ""
        if not hasattr(record, "fields"):
            record.fields = {}
        return True


class KeyValueFormatter(logging.Formatter):
    """Render logs as compact key=value records."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        items: list[tuple[str, Any]] = [
            ("ts", datetime.fromtimestamp(record.created, UTC).isoformat()),
            ("level", record.levelname),
            ("logger", record.name),
            ("log_id", getattr(record, "log_id", "-")),
        ]
        event = getattr(record, "event", "")
        if event:
            items.append(("event", event))
        fields = getattr(record, "fields", {})
        if isinstance(fields, dict):
            items.extend((str(key), value) for key, value in fields.items())
        if record.message and record.message != event:
            items.append(("msg", record.message))
        if record.exc_info:
            items.append(("exception", self.formatException(record.exc_info)))
        if record.stack_info:
            items.append(("stack", self.formatStack(record.stack_info)))
        return " ".join(f"{key}={_format_value(value)}" for key, value in items)


def configure_logging(level_name: str = "INFO") -> None:
    """Configure process-wide logging without disrupting pytest capture handlers."""
    _install_record_factory()
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    request_filter = _get_or_create_filter(root)
    formatter = KeyValueFormatter()

    stream_handlers = [
        handler for handler in root.handlers if isinstance(handler, logging.StreamHandler)
    ]
    if not stream_handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.addFilter(request_filter)
        handler.setFormatter(formatter)
        root.addHandler(handler)
        return

    for handler in stream_handlers:
        if not any(isinstance(item, RequestLogFilter) for item in handler.filters):
            handler.addFilter(request_filter)
        # Pytest's capture handler keeps its own formatter for assertions.
        if handler.__class__.__module__.startswith("_pytest."):
            continue
        handler.setFormatter(formatter)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Log a stable event with sanitized structured fields."""
    logger.log(
        level,
        event,
        extra={"event": event, "fields": _sanitize_fields(fields)},
        exc_info=exc_info,
    )


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _install_record_factory() -> None:
    global _RECORD_FACTORY_INSTALLED
    if _RECORD_FACTORY_INSTALLED:
        return
    original_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original_factory(*args, **kwargs)
        if not hasattr(record, "log_id"):
            record.log_id = get_log_id()
        return record

    logging.setLogRecordFactory(record_factory)
    _RECORD_FACTORY_INSTALLED = True


def _get_or_create_filter(root: logging.Logger) -> RequestLogFilter:
    for item in root.filters:
        if isinstance(item, RequestLogFilter):
            return item
    request_filter = RequestLogFilter()
    root.addFilter(request_filter)
    return request_filter


def _sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        clean_key = str(key)
        if _is_sensitive_key(clean_key):
            safe[clean_key] = "[redacted]"
        else:
            safe[clean_key] = _sanitize_value(value)
    return safe


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _is_sensitive_key(str(key)) else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and len(value) > 500:
        return f"{value[:500]}...[truncated]"
    return value


def _is_sensitive_key(key: str) -> bool:
    lower_key = key.lower()
    if lower_key in {"prompt_tokens", "completion_tokens", "total_tokens", "max_tokens"}:
        return False
    return any(part in lower_key for part in SENSITIVE_FIELD_PARTS)


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    text = str(value)
    if text == "" or any(ch.isspace() for ch in text) or any(ch in text for ch in "\"'={}[]"):
        return json.dumps(text, ensure_ascii=False)
    return text
