"""Shared truncation helpers for context and summary building."""

SUMMARY_TRUNCATION_MARKER = "...(summary truncated)"


def truncate_with_marker(
    value: str,
    max_chars: int,
    marker: str = SUMMARY_TRUNCATION_MARKER,
) -> str:
    """Truncate text while making information loss visible to downstream code."""
    text = value or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return marker[:max_chars]
    return text[: max_chars - len(marker)].rstrip() + marker
