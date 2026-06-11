"""Reading strategy decisions shared by pipelines."""

from app.shared_infra.models import DocumentSizeTier, ReadingStrategy


def is_fast_track(size_tier: DocumentSizeTier | str) -> bool:
    tier = DocumentSizeTier(size_tier)
    return tier in {DocumentSizeTier.TINY, DocumentSizeTier.SHORT}


def decide_search_strategy(group: str, size_tier: DocumentSizeTier | str, intent_type: str) -> ReadingStrategy:
    """Apply the phase-two search reading strategy matrix."""
    tier = DocumentSizeTier(size_tier)
    if group == "source_notes":
        return ReadingStrategy.SKIP
    if group == "maps":
        return ReadingStrategy.STRUCTURED_SECTIONS
    if is_fast_track(tier):
        return ReadingStrategy.FULL
    if group == "core_hits":
        if tier == DocumentSizeTier.MEDIUM:
            return ReadingStrategy.FULL
        return ReadingStrategy.KEY_SECTIONS
    if group == "related_cards":
        if intent_type in {"topic_scan", "compare"}:
            return ReadingStrategy.KEY_SECTIONS
        return ReadingStrategy.SUMMARY
    return ReadingStrategy.SUMMARY
