"""Content extraction helpers driven by MarkdownStructure."""

from __future__ import annotations

import re
from typing import Any

from app.shared_infra.markdown_parser import parse_frontmatter_and_body
from app.shared_infra.models import MarkdownStructure
from app.shared_infra.truncation import truncate_with_marker


def extract_body(content: str) -> str:
    """Return markdown body without YAML frontmatter."""
    _, body = parse_frontmatter_and_body(content)
    return body


def extract_summary(content: str, structure: MarkdownStructure, max_chars: int = 500) -> str:
    """Extract a compact summary from frontmatter or the first useful paragraph."""
    fm = structure.frontmatter or {}
    for key in ("doc_summary", "summary", "description"):
        value = fm.get(key)
        if isinstance(value, str) and value.strip():
            return truncate_with_marker(value.strip(), max_chars)

    body = extract_body(content)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    for paragraph in paragraphs:
        if not paragraph.startswith("#"):
            return truncate_with_marker(paragraph, max_chars)
    return truncate_with_marker(body, max_chars)


def extract_key_sections(
    content: str,
    structure: MarkdownStructure,
    keywords: list[str],
    intent_type: str,
    max_sections: int = 3,
) -> str:
    """Extract 2-3 sections whose headings best match query and intent hints."""
    body = extract_body(content)
    lines = body.splitlines()
    if not structure.headings:
        return truncate_with_marker(body, 2500)

    intent_hints = {
        "concept": ["definition", "overview", "principle", "core"],
        "topic_scan": ["overview", "summary", "landscape", "core"],
        "compare": ["compare", "difference", "versus"],
        "relation": ["relation", "dependency", "link"],
        "source_trace": ["source", "citation", "reference"],
    }
    needles = [k.lower() for k in keywords if k] + [
        h.lower() for h in intent_hints.get(intent_type, [])
    ]

    scored: list[tuple[int, int]] = []
    for heading in structure.headings:
        title = heading.title.lower()
        score = sum(1 for needle in needles if needle and needle in title)
        if score:
            scored.append((score, heading.section_id))
    if not scored:
        scored = [(1, h.section_id) for h in structure.headings[:max_sections]]

    selected = [sid for _, sid in sorted(scored, reverse=True)[:max_sections]]
    chunks = [_section_text(lines, structure, sid) for sid in selected]
    return "\n\n".join(chunk for chunk in chunks if chunk).strip()


def extract_structured_sections(content: str, structure: MarkdownStructure) -> str:
    """Read structured map fields from frontmatter first, then known body sections."""
    fm = structure.frontmatter or {}
    pieces: list[str] = []
    for field in ("core_concepts", "reading_path", "key_relations", "source_materials", "linked_maps"):
        value = fm.get(field)
        if value:
            pieces.append(f"## {field}\n{_stringify(value)}")
    if pieces:
        return "\n\n".join(pieces)

    body = extract_body(content)
    headings = ["核心概念", "推荐阅读路径", "关键关系", "来源材料", "关联入口"]
    pattern = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    for index, match in enumerate(matches):
        title = match.group(2)
        if not any(h in title for h in headings):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        pieces.append(body[match.start():end].strip())
    return "\n\n".join(pieces)


def extract_paragraphs(
    content: str,
    structure: MarkdownStructure,
    para_range: list[int],
    buffer: int = 1,
    min_chars: int = 200,
) -> str:
    """Extract paragraph range with a section-local buffer."""
    body = extract_body(content)
    lines = body.splitlines()
    paragraphs = structure.paragraphs or []
    if not paragraphs:
        return truncate_with_marker(body, 3000)

    start_id = max(0, para_range[0] if para_range else 0)
    end_id = min(len(paragraphs) - 1, para_range[1] if len(para_range) > 1 else start_id)
    section_id = paragraphs[start_id].section_id if start_id < len(paragraphs) else None

    section_paras = [
        p for p in paragraphs
        if p.section_id == section_id and start_id - buffer <= p.para_id <= end_id + buffer
    ]
    if not section_paras:
        section_paras = paragraphs[start_id : end_id + 1]

    text = "\n\n".join(
        "\n".join(lines[p.line_start - 1 : p.line_end]).strip()
        for p in section_paras
    ).strip()

    if len(text) >= min_chars:
        return truncate_with_marker(text, 8000)
    if section_id is not None:
        return truncate_with_marker(_section_text(lines, structure, section_id), 8000)
    return truncate_with_marker(body, 3000)


def _section_text(lines: list[str], structure: MarkdownStructure, section_id: int | None) -> str:
    if section_id is None:
        return ""
    heading = next((h for h in structure.headings if h.section_id == section_id), None)
    if heading is None:
        return ""
    later = [
        h.line_number for h in structure.headings
        if h.line_number > heading.line_number and h.level <= heading.level
    ]
    end = min(later) - 1 if later else len(lines)
    return "\n".join(lines[heading.line_number - 1 : end]).strip()


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- {key}: {val}" for key, val in value.items())
    return str(value)
