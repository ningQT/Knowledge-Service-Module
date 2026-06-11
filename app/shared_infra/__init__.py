"""Shared infrastructure for write and search phase-two pipelines."""

from app.shared_infra.budget import create_budget, enforce_budget, is_over_budget, update_budget
from app.shared_infra.content_extractor import (
    extract_body,
    extract_key_sections,
    extract_paragraphs,
    extract_structured_sections,
    extract_summary,
)
from app.shared_infra.markdown_parser import (
    classify_document_size,
    generate_toc,
    parse_frontmatter_and_body,
    parse_markdown_structure,
)
from app.shared_infra.models import (
    BudgetStatus,
    DocumentSizeTier,
    HeadingItem,
    MarkdownStructure,
    ParagraphItem,
    ReadingStrategy,
)
from app.shared_infra.strategy import decide_search_strategy, is_fast_track
from app.shared_infra.truncation import SUMMARY_TRUNCATION_MARKER, truncate_with_marker

__all__ = [
    "BudgetStatus",
    "DocumentSizeTier",
    "HeadingItem",
    "MarkdownStructure",
    "ParagraphItem",
    "ReadingStrategy",
    "SUMMARY_TRUNCATION_MARKER",
    "classify_document_size",
    "create_budget",
    "decide_search_strategy",
    "enforce_budget",
    "extract_body",
    "extract_key_sections",
    "extract_paragraphs",
    "extract_structured_sections",
    "extract_summary",
    "generate_toc",
    "is_fast_track",
    "is_over_budget",
    "parse_frontmatter_and_body",
    "parse_markdown_structure",
    "update_budget",
    "truncate_with_marker",
]
