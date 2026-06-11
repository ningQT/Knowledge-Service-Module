"""Markdown structure parser shared by write and search pipelines."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import yaml

from app.schema.parser import _normalize_yaml_value
from app.shared_infra.exceptions import EmptyContentError, StructureParseError, YAMLParseError
from app.shared_infra.models import DocumentSizeTier, HeadingItem, MarkdownStructure, ParagraphItem

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_frontmatter_and_body(content: str) -> tuple[dict[str, Any] | None, str]:
    """Split YAML frontmatter from body without changing body line coordinates."""
    if content == "":
        return None, ""

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, content.strip()

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None, content.strip()

    yaml_text = "\n".join(lines[1:end_index]).strip()
    body = "\n".join(lines[end_index + 1 :]).strip()
    if not yaml_text:
        return None, body

    try:
        loaded = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise YAMLParseError(str(exc)) from exc
    if not isinstance(loaded, dict):
        return None, body
    return _normalize_yaml_value(loaded), body


def parse_markdown_structure(
    content: str,
    mode: str = "full",
    max_level: int = 4,
) -> MarkdownStructure:
    """Parse markdown into a lightweight or full structural model."""
    if not content or not content.strip():
        raise EmptyContentError()
    if mode not in {"full", "lite"}:
        raise StructureParseError(f"Unsupported mode: {mode}")
    max_level = max(1, min(max_level, 6))

    frontmatter, body = parse_frontmatter_and_body(content)
    body_lines = body.splitlines()
    headings = _parse_headings(body_lines, max_level)
    paragraphs = _parse_paragraphs(body_lines, headings) if mode == "full" else None
    special_elements = _count_special_elements(body_lines, mode)

    return MarkdownStructure(
        total_chars=len(content),
        total_lines=len(body_lines),
        heading_count=len(headings),
        estimated_reading_time=max(1, round(len(body) / 500)) if mode == "full" else 0,
        size_tier=classify_document_size(len(content)),
        frontmatter=frontmatter,
        headings=headings,
        paragraphs=paragraphs,
        special_elements=special_elements,
        toc=generate_toc(headings, max_level=max_level),
    )


def classify_document_size(total_chars: int) -> DocumentSizeTier:
    if total_chars < 2000:
        return DocumentSizeTier.TINY
    if total_chars < 5000:
        return DocumentSizeTier.SHORT
    if total_chars < 15000:
        return DocumentSizeTier.MEDIUM
    if total_chars < 50000:
        return DocumentSizeTier.LONG
    return DocumentSizeTier.XLONG


def generate_toc(headings: list[HeadingItem], max_level: int = 4) -> str:
    """Generate a compact indented table of contents."""
    lines = []
    for heading in headings:
        if heading.level <= max_level:
            lines.append(f"{'  ' * (heading.level - 1)}{heading.title}")
    return "\n".join(lines)


def _parse_headings(lines: list[str], max_level: int) -> list[HeadingItem]:
    headings: list[HeadingItem] = []
    stack: list[HeadingItem] = []

    for line_number, line in enumerate(lines, 1):
        match = HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if level > max_level:
            continue
        title = match.group(2).strip()
        while stack and stack[-1].level >= level:
            stack.pop()
        parent_id = stack[-1].section_id if stack else None
        item = HeadingItem(
            section_id=len(headings),
            title=title,
            level=level,
            line_number=line_number,
            parent_id=parent_id,
        )
        headings.append(item)
        if parent_id is not None:
            parent = headings[parent_id]
            parent.child_count += 1
        stack.append(item)
    return headings


def _parse_paragraphs(lines: list[str], headings: list[HeadingItem]) -> list[ParagraphItem]:
    heading_by_line = {heading.line_number: heading for heading in headings}
    paragraphs: list[ParagraphItem] = []
    current_section: int | None = None
    start: int | None = None
    buffer: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal start, buffer
        if start is None or not buffer:
            start = None
            buffer = []
            return
        text = "\n".join(buffer).strip()
        if text:
            paragraphs.append(
                ParagraphItem(
                    para_id=len(paragraphs),
                    section_id=current_section,
                    line_start=start,
                    line_end=end_line,
                    char_count=len(text),
                )
            )
        start = None
        buffer = []

    for line_number, line in enumerate(lines, 1):
        if line_number in heading_by_line:
            flush(line_number - 1)
            current_section = heading_by_line[line_number].section_id
            continue
        if not line.strip():
            flush(line_number - 1)
            continue
        if start is None:
            start = line_number
        buffer.append(line)
    flush(len(lines))
    return paragraphs


def _count_special_elements(lines: list[str], mode: str) -> dict[str, Any]:
    counters = Counter()
    details: dict[str, list[int]] = {"code_blocks": [], "tables": [], "links": []}
    in_code = False
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            counters["code_blocks"] += 1
            if mode == "full":
                details["code_blocks"].append(line_number)
        if "|" in line and not in_code:
            counters["tables"] += 1
            if mode == "full":
                details["tables"].append(line_number)
        if "[[" in line or "](" in line:
            counters["links"] += 1
            if mode == "full":
                details["links"].append(line_number)
    if mode == "lite":
        return dict(counters)
    return {"counts": dict(counters), "lines": details}
