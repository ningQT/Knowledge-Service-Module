"""Models for map/card driven answer synthesis."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceCard(BaseModel):
    path: str
    title: str = ""
    source_note_paths: list[str] = Field(default_factory=list)
    map_paths: list[str] = Field(default_factory=list)
    relation_chain: list[str] = Field(default_factory=list)
    summary: str = ""


class Citation(BaseModel):
    id: str
    source_note_path: str | None = None
    source_title: str = ""
    evidence_cards: list[str] = Field(default_factory=list)
    relation_chain: list[str] = Field(default_factory=list)
    traced: bool = True
    note: str = ""


class ProcessSummary(BaseModel):
    step: str
    title: str
    summary: str
    details: dict = Field(default_factory=dict)


class CardSummary(BaseModel):
    card_path: str = ""
    title: str = ""
    relevance_to_query: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_citation_ids: list[str] = Field(default_factory=list)
    conflicts_or_limits: list[str] = Field(default_factory=list)


class BatchSummary(BaseModel):
    batch_id: str = ""
    card_paths: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class TopicSummary(BaseModel):
    topic: str = ""
    batch_ids: list[str] = Field(default_factory=list)
    card_paths: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class AnswerSection(BaseModel):
    id: str = ""
    title: str = ""
    summary: str = ""
    content_md: str = ""
    key_points: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    batch_ids: list[str] = Field(default_factory=list)
    card_paths: list[str] = Field(default_factory=list)
    coverage_status: str = "covered"
    remaining_card_count: int = 0
    expandable: bool = True
    continuation_hint: str = ""


class CoverageLedger(BaseModel):
    maps_found: int = 0
    cards_found: int = 0
    cards_read: int = 0
    cards_summarized: int = 0
    cards_used_for_synthesis: int = 0
    cards_skipped_by_budget: int = 0
    summary_batches_total: int = 0
    summary_batches_used: int = 0
    summary_batches_failed: int = 0
    citations_total: int = 0
    citations_traced: int = 0
    citations_untraced: int = 0


class AnswerResult(BaseModel):
    query: str
    answer: str
    answer_md: str = ""
    key_points: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    process_summaries: list[ProcessSummary] = Field(default_factory=list)
    coverage_ledger: CoverageLedger = Field(default_factory=CoverageLedger)
    batch_summaries: list[BatchSummary] = Field(default_factory=list)
    topic_summaries: list[TopicSummary] = Field(default_factory=list)
    sections: list[AnswerSection] = Field(default_factory=list)
    search_result: dict | None = None
    comprehension: dict | None = None
    warnings: list[str] = Field(default_factory=list)


class BatchSummarizationOutput(BaseModel):
    card_summaries: list[CardSummary] = Field(default_factory=list)
    batch_summary: BatchSummary = Field(default_factory=BatchSummary)


class AnswerSynthesisOutput(BaseModel):
    answer: str = ""
    answer_md: str = ""
    key_points: list[str] = Field(default_factory=list)
    sections: list[AnswerSection] = Field(default_factory=list)
    citation_notes: list[dict] = Field(default_factory=list)
    process_summaries: list[dict] = Field(default_factory=list)


class SectionSynthesisOutput(BaseModel):
    section: AnswerSection = Field(default_factory=AnswerSection)


class OverviewSynthesisOutput(BaseModel):
    answer: str = ""
    key_points: list[str] = Field(default_factory=list)
