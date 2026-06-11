"""Normalize note metadata for indexing without losing the raw frontmatter."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
LIST_FIELDS = ("domain", "kind", "aliases", "concepts", "sources")
FACET_FIELDS = ("domain", "kind", "aliases", "concepts", "sources")


@dataclass(frozen=True)
class NormalizedMetadata:
    """Normalized frontmatter plus indexing helpers."""

    frontmatter: dict[str, Any]
    raw_frontmatter: dict[str, Any]
    facets: list[tuple[str, str]] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def first(self, field_name: str) -> str | None:
        """Return the first normalized value for a multi-value field."""
        values = self.frontmatter.get(field_name)
        if isinstance(values, list):
            return values[0] if values else None
        if values is None:
            return None
        text = str(values).strip()
        return text or None


def normalize_metadata(frontmatter: dict[str, Any] | None) -> NormalizedMetadata:
    """Normalize KSM note metadata while preserving the original dictionary."""
    raw = copy.deepcopy(frontmatter or {})
    normalized = copy.deepcopy(frontmatter or {})
    facets: list[tuple[str, str]] = []
    search_terms: list[str] = []
    warnings: list[str] = []

    for field_name in LIST_FIELDS:
        values = normalize_metadata_values(raw.get(field_name))
        normalized[field_name] = values
        if field_name in FACET_FIELDS:
            facets.extend((field_name, value) for value in values)
        search_terms.extend(values)
        if isinstance(raw.get(field_name), dict):
            warnings.append(f"{field_name}_object_normalized")

    graph_layer = _coerce_graph_layer(raw.get("graph_layer", normalized.get("graph_layer", 0)))
    normalized["graph_layer"] = graph_layer
    normalized.setdefault("verification", "unverified")
    normalized.setdefault("status", "active")
    normalized["raw_frontmatter"] = raw
    if warnings:
        normalized["metadata_warnings"] = warnings

    return NormalizedMetadata(
        frontmatter=normalized,
        raw_frontmatter=raw,
        facets=_dedupe_pairs(facets),
        search_terms=_dedupe(search_terms),
        warnings=warnings,
    )


def normalize_metadata_values(value: Any) -> list[str]:
    """Return a stable list of clean text values from scalar/list metadata."""
    values: list[str] = []
    for item in _iter_metadata_values(value):
        values.extend(_clean_metadata_item(item))
    return _dedupe(values)


def clean_wikilink_target(value: str) -> str:
    """Clean a wikilink target or plain path into searchable text."""
    text = str(value or "").strip()
    match = WIKILINK_RE.fullmatch(text)
    if match:
        text = match.group(1).strip()
    text = text.strip()
    if text.endswith(".md"):
        text = normalize_metadata_path(text)
    return text


def normalize_metadata_path(value: str) -> str:
    """Normalize path-like metadata while preserving display-friendly values."""
    text = str(value or "").replace("\\", "/").strip()
    return text.strip("/")


def extract_wikilinks_from_value(value: Any) -> list[dict[str, str]]:
    """Extract wikilinks from a metadata value, including nested lists and dicts."""
    links: list[dict[str, str]] = []
    for item in _iter_metadata_values(value):
        text = str(item)
        for match in WIKILINK_RE.finditer(text):
            target = match.group(1).strip()
            alias = (match.group(2) or "").strip()
            if target:
                links.append({"target": target, "alias": alias})
    return links


def primary_metadata_value(value: Any) -> str | None:
    """Return the first normalized value for a scalar/list metadata field."""
    values = normalize_metadata_values(value)
    return values[0] if values else None


def _iter_metadata_values(value: Any):
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_metadata_values(item)
        return
    if isinstance(value, (tuple, set)):
        for item in value:
            yield from _iter_metadata_values(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_metadata_values(item)
        return
    yield value


def _clean_metadata_item(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []

    match = WIKILINK_RE.fullmatch(text)
    if match:
        target = _clean_plain_value(match.group(1))
        alias = _clean_plain_value(match.group(2) or "")
        return [item for item in (target, alias) if item]

    replaced = WIKILINK_RE.sub(lambda m: _clean_plain_value(m.group(1)), text)
    cleaned = _clean_plain_value(replaced)
    return [cleaned] if cleaned else []


def _clean_plain_value(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\\", "/")
    text = re.sub(r"\s+", " ", text)
    if text.endswith(".md") and "/" not in text:
        text = Path(text).stem
    return text.strip()


def _coerce_graph_layer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _dedupe_pairs(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for field_name, value in values:
        key = (field_name, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append((field_name, value))
    return result
