"""Frontmatter pydantic models for KSM knowledge objects."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class FrontmatterBase(BaseModel):
    """Base frontmatter model with standard fields.

    Reference: 详细设计文档 Section 5.2
    """

    type: str = Field(description="Note type: source, card, map")
    domain: str | None = Field(default=None, description="Knowledge domain")
    kind: str | None = Field(default=None, description="Sub-category")
    graph_layer: int = Field(description="Graph layer: 0=inbox, 1=source, 2=card, 3=map")
    graph_role: str = Field(description="Graph role: inbox, source, concept, method, index")
    verification: str = Field(default="unverified", description="verified, unverified, draft")
    status: str = Field(default="active", description="draft, active, archived")
    sources: list[str] = Field(default_factory=list, description="Source note paths")
    concepts: list[str] = Field(default_factory=list, description="Core concepts for indexing")
    original_doc: str | None = Field(default=None, description="Path to original document")
    extracted_cards: list[str] = Field(default_factory=list, description="Cards extracted from source")
    card_count: int | None = Field(default=None, description="Number of extracted cards")
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last update timestamp",
    )


class SourceFrontmatter(FrontmatterBase):
    """Frontmatter for source notes (graph_layer=1)."""

    type: str = "source"
    graph_layer: int = 1
    graph_role: str = "source"
    doc_title: str | None = Field(default=None, description="LLM-generated document title")
    doc_summary: str | None = Field(default=None, description="LLM-generated document summary")
    doc_type: str | None = Field(default=None, description="Document type")
    main_topic: str | None = Field(default=None, description="Main topic")
    extractable_knowledge_points: list[str] = Field(
        default_factory=list,
        description="Knowledge points identified by source-note analysis",
    )


class CardFrontmatter(FrontmatterBase):
    """Frontmatter for knowledge cards (graph_layer=2)."""

    type: str = "card"
    graph_layer: int = 2
    graph_role: str = "concept"


class MapFrontmatter(FrontmatterBase):
    """Frontmatter for knowledge maps (graph_layer=3)."""

    type: str = "map"
    graph_layer: int = 3
    graph_role: str = "index"
    core_concepts: list[dict] = Field(default_factory=list, description="Core concepts with roles")
    reading_path: list[dict] = Field(default_factory=list, description="Recommended reading path")
    key_relations: list[dict] = Field(default_factory=list, description="Key relation triples")
    source_materials: list[dict] = Field(default_factory=list, description="Source materials")
    linked_maps: list[dict] = Field(default_factory=list, description="Related map entries")
