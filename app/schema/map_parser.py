"""Knowledge map structure parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path

from app.schema.parser import parse_frontmatter

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")
MAP_STRUCTURE_FIELDS = [
    "core_concepts",
    "reading_path",
    "key_relations",
    "source_materials",
    "linked_maps",
]
SECTION_ALIASES = {
    "core_concepts": ["核心概念", "Core Concepts"],
    "reading_path": ["推荐阅读路径", "Reading Path", "Recommended Reading Path"],
    "key_relations": ["关键关系", "Key Relations", "Relations"],
    "source_materials": ["来源材料", "Source Materials", "Sources"],
    "linked_maps": ["关联入口", "Linked Maps", "Related Maps", "Entries"],
}


def parse_map_structure(content: str) -> dict:
    """Parse v4 map structure, preferring frontmatter when it is complete enough."""
    frontmatter, body = parse_frontmatter(content)
    structure = structure_from_frontmatter(frontmatter)
    if has_map_structure(structure):
        return structure
    return parse_map_body_sections(body)


def parse_map_body_sections(body: str) -> dict:
    """Parse v4 map structure from markdown body sections only."""
    sections = _split_sections(body)
    if not any(alias in sections for aliases in SECTION_ALIASES.values() for alias in aliases):
        return empty_map_structure()

    return {
        "core_concepts": _parse_bullets(_section_text(sections, "core_concepts")),
        "reading_path": _parse_bullets(_section_text(sections, "reading_path"), ordered=True),
        "key_relations": _parse_relations(_section_text(sections, "key_relations")),
        "source_materials": _parse_bullets(_section_text(sections, "source_materials")),
        "linked_maps": _parse_bullets(_section_text(sections, "linked_maps")),
    }


def structure_from_frontmatter(frontmatter: dict) -> dict:
    """Extract v4 map structure fields from frontmatter."""
    return {
        "core_concepts": _as_list(frontmatter.get("core_concepts")),
        "reading_path": _as_list(frontmatter.get("reading_path")),
        "key_relations": _as_list(frontmatter.get("key_relations")),
        "source_materials": _as_list(frontmatter.get("source_materials")),
        "linked_maps": _as_list(frontmatter.get("linked_maps")),
    }


def empty_map_structure() -> dict:
    """Return an empty v4 map structure."""
    return {
        "core_concepts": [],
        "reading_path": [],
        "key_relations": [],
        "source_materials": [],
        "linked_maps": [],
    }


def has_map_structure(structure: dict) -> bool:
    """Return true when a map has enough structure to expand from."""
    return bool(structure.get("core_concepts") or structure.get("reading_path"))


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str) and value.strip():
        return [{"title": value.strip()}]
    return []


def _split_sections(body: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end].strip()
    return sections


def _section_text(sections: dict[str, str], field: str) -> str:
    for alias in SECTION_ALIASES[field]:
        if alias in sections:
            return sections[alias]
    return ""


def _parse_bullets(text: str, ordered: bool = False) -> list[dict]:
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        order_match = re.match(r"^(\d+)[.)]\s*(.+)$", stripped)
        is_bullet = stripped.startswith(("-", "*")) or bool(order_match)
        if not stripped or not is_bullet:
            continue
        body = order_match.group(2).strip() if order_match else stripped.lstrip("-* ").strip()
        title = _extract_wikilink(body) or _strip_inline_note(body)
        item = {"title": Path(title).stem if title.endswith(".md") else title}
        if ordered and order_match:
            item["order"] = int(order_match.group(1))
        if title.endswith(".md") or "/" in title:
            item["path"] = title
        role_match = re.search(r"\(([^)]+)\)", body)
        if role_match:
            item["role"] = role_match.group(1).strip()
        reason = _strip_wikilinks(body)
        reason = re.sub(r"\([^)]+\)", "", reason).strip(" -:：")
        if reason and reason != item["title"]:
            item["reason"] = reason
        items.append(item)
    return items


def _parse_relations(text: str) -> list[dict]:
    table_rows = _parse_relation_table(text)
    if table_rows:
        return table_rows

    relations = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if not stripped:
            continue
        arrow_match = re.match(r"(.+?)\s*(?:--|->|→|=>)\s*([^->→=]+?)\s*(?:-->|->|→|=>)\s*(.+)", stripped)
        if arrow_match:
            relations.append({
                "from": _clean_cell(arrow_match.group(1)),
                "relation": _clean_cell(arrow_match.group(2)),
                "to": _clean_cell(arrow_match.group(3)),
                "description": stripped,
            })
        else:
            relations.append({"description": stripped})
    return relations


def _extract_wikilink(text: str) -> str | None:
    match = WIKILINK_RE.search(text)
    return match.group(1).strip() if match else None


def _strip_inline_note(text: str) -> str:
    text = re.sub(r"^[\-\*\d.)\s]+", "", text).strip()
    text = re.split(r"\s+[（(]|[：:：-]\s+", text, maxsplit=1)[0].strip()
    return text


def _strip_wikilinks(text: str) -> str:
    return WIKILINK_RE.sub(lambda match: match.group(1).strip(), text)


def _parse_relation_table(text: str) -> list[dict]:
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(rows) < 2 or not TABLE_SEPARATOR_RE.match(rows[1]):
        return []
    headers = [_normalize_header(cell) for cell in _split_table_row(rows[0])]
    parsed: list[dict] = []
    for row in rows[2:]:
        cells = _split_table_row(row)
        if len(cells) < len(headers):
            continue
        data = {headers[index]: _clean_cell(cells[index]) for index in range(len(headers))}
        item: dict = {}
        for source_key in ("from", "source", "起点"):
            if source_key in data:
                item["from"] = data[source_key]
                break
        for relation_key in ("relation", "rel", "关系", "type"):
            if relation_key in data:
                item["relation"] = data[relation_key]
                break
        for target_key in ("to", "target", "终点"):
            if target_key in data:
                item["to"] = data[target_key]
                break
        for evidence_key in ("evidence", "证据", "依据"):
            if evidence_key in data:
                item["evidence"] = data[evidence_key]
                break
        if item:
            parsed.append(item)
    return parsed


def _split_table_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _normalize_header(value: str) -> str:
    return value.strip().lower()


def _clean_cell(value: str) -> str:
    return _strip_wikilinks(value).strip()
