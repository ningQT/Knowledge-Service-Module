"""Markdown frontmatter parsing and serialization helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import yaml


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown document."""
    stripped = content.strip()
    if not stripped.startswith("---"):
        return {}, stripped

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, stripped

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}, stripped

    yaml_text = "\n".join(lines[1:end_index]).strip()
    body = "\n".join(lines[end_index + 1 :]).strip()
    if not yaml_text:
        return {}, body

    loaded = yaml.safe_load(yaml_text) or {}
    if not isinstance(loaded, dict):
        return {}, body

    return _normalize_yaml_value(loaded), body


def serialize_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter and markdown body."""
    cleaned = {key: value for key, value in frontmatter.items() if value is not None}
    yaml_text = yaml.safe_dump(
        cleaned,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def _normalize_yaml_value(value: Any) -> Any:
    """Normalize PyYAML-native values into JSON-serializable frontmatter values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_yaml_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_yaml_value(item)
            for key, item in value.items()
        }
    return value
