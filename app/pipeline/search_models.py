"""Pydantic models for the search pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.shared_infra.models import BudgetStatus, MarkdownStructure, ReadingStrategy


class AnchorCandidate(BaseModel):
    """A candidate anchor node from anchor positioning."""

    path: str
    title: str
    score: float
    match_type: str  # title_exact, title_contains, concepts_field, source_fts, map_fts, map_title_contains, fts_fallback
    match_keyword: str = ""
    graph_layer: int = 0
    graph_role: str | None = None
    domain: str | None = None
    kind: str | None = None
    verification: str = "unverified"
    frontmatter: dict = Field(default_factory=dict)


class ExpansionNode(BaseModel):
    """A node discovered during graph expansion."""

    path: str
    title: str
    graph_layer: int = 0
    graph_role: str | None = None
    domain: str | None = None
    kind: str | None = None
    verification: str = "unverified"
    frontmatter: dict = Field(default_factory=dict)
    hop_distance: int = 0
    rel_type_to_anchor: str | None = None
    score: float = 0.0
    match_type: str = ""
    concepts: list[str] = Field(default_factory=list)


class ExpansionResult(BaseModel):
    """Result of graph expansion from anchors."""

    nodes: dict[str, ExpansionNode] = Field(default_factory=dict)
    edges: list[dict] = Field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0
    max_depth_reached: int = 0


class OrganizedCandidates(BaseModel):
    """Candidates organized into 4 groups."""

    core_hits: list[dict] = Field(default_factory=list)
    related_cards: list[dict] = Field(default_factory=list)
    source_notes: list[dict] = Field(default_factory=list)
    maps: list[dict] = Field(default_factory=list)


class SearchStats(BaseModel):
    """Statistics for a search result."""

    core_count: int = 0
    related_count: int = 0
    source_count: int = 0
    map_count: int = 0
    total: int = 0
    fallback_mode: bool = False
    search_path: str = "card_scatter"
    map_sourced_count: int = 0


class NodeStructure(BaseModel):
    """Structure and reading result for one search result node."""

    instance_id: str | None = None
    path: str
    title: str = ""
    group: str
    note_type: str | None = None
    graph_layer: int = 0
    graph_role: str | None = None
    frontmatter: dict = Field(default_factory=dict)
    structure: MarkdownStructure | None = None
    strategy: ReadingStrategy = ReadingStrategy.FULL
    content: str | None = None
    missing: bool = False
    is_primary: bool | None = None
    truncated: bool = False


class ConceptCoverage(BaseModel):
    total_query_concepts: int = 0
    covered_concepts: list[str] = Field(default_factory=list)
    gap_concepts: list[str] = Field(default_factory=list)
    coverage_ratio: float = 0.0


class DuplicatePair(BaseModel):
    node_a: str
    node_b: str
    similarity: float
    overlap_concepts: list[str] = Field(default_factory=list)


class HierarchyRelation(BaseModel):
    parent: str
    child: str
    relation_type: str
    confidence: float = 1.0


class MapInsight(BaseModel):
    source_map: str
    map_title: str = ""
    is_primary: bool = False
    insight_preview: str = ""
    core_concepts: list[dict] = Field(default_factory=list)
    key_relations: list[dict] = Field(default_factory=list)
    reading_path: list[dict] = Field(default_factory=list)


class ComprehensionResult(BaseModel):
    """Document reading comprehension output for search results."""

    documents: list[NodeStructure] = Field(default_factory=list)
    concept_coverage: ConceptCoverage | None = None
    duplicates: list[DuplicatePair] = Field(default_factory=list)
    hierarchy: list[HierarchyRelation] = Field(default_factory=list)
    map_insights: list[MapInsight] = Field(default_factory=list)
    enhanced_prompt_context: str | None = None
    budget_status: BudgetStatus | None = None


class SearchResult(BaseModel):
    """Complete search result — structured knowledge node package."""

    query: str
    intent_type: str
    query_context: dict = Field(default_factory=dict)
    core_hits: list[dict] = Field(default_factory=list)
    related_cards: list[dict] = Field(default_factory=list)
    source_notes: list[dict] = Field(default_factory=list)
    maps: list[dict] = Field(default_factory=list)
    map_priority: bool = False
    key_relations: list[dict] = Field(default_factory=list)
    stats: SearchStats = Field(default_factory=SearchStats)
    comprehension: ComprehensionResult | None = None
