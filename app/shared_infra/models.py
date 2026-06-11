"""Shared models for document structure, reading strategy, and budgets."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DocumentSizeTier(StrEnum):
    TINY = "tiny"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    XLONG = "xlong"


class ReadingStrategy(StrEnum):
    FULL = "full"
    KEY_SECTIONS = "key_sections"
    SUMMARY = "summary"
    SECTION_BATCH = "section_batch"
    STRUCTURED_SECTIONS = "structured_sections"
    SKIP = "skip"


class HeadingItem(BaseModel):
    section_id: int
    title: str
    level: int
    line_number: int
    parent_id: int | None = None
    child_count: int = 0


class ParagraphItem(BaseModel):
    para_id: int
    section_id: int | None = None
    line_start: int
    line_end: int
    char_count: int


class MarkdownStructure(BaseModel):
    total_chars: int
    total_lines: int
    heading_count: int
    estimated_reading_time: int = 0
    size_tier: DocumentSizeTier
    frontmatter: dict[str, Any] | None = None
    headings: list[HeadingItem] = Field(default_factory=list)
    paragraphs: list[ParagraphItem] | None = None
    special_elements: dict[str, Any] = Field(default_factory=dict)
    toc: str = ""


class BudgetStatus(BaseModel):
    limit: int
    used: int = 0
    remaining: int = 0
    utilization: float = 0.0
