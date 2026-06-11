"""Pydantic models for LLM output structures."""

from pydantic import AliasChoices, BaseModel, Field, model_validator

MAX_DOC_TOPICS = 5
MAX_SOURCE_KNOWLEDGE_POINTS = 20
MAX_SOURCE_CONCEPTS = 15
MAX_CARD_CONCEPTS = 8
MAX_CARD_WIKILINKS = 10
MAX_MAP_CONCEPTS = 15
MAX_MAP_CORE_CONCEPTS = 10
MAX_MAP_READING_PATH = 10
MAX_MAP_KEY_RELATIONS = 20
MAX_MAP_LINKED_MAPS = 10
MAX_RELATION_CONNECTIONS = 10
STEP2_MAX_CANDIDATE_CARDS = 8


def _limit(values: list, max_items: int) -> list:
    return values[:max_items]


class TokenUsage(BaseModel):
    """Token usage reported by an OpenAI-compatible response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResult(BaseModel):
    """Structured LLM response used by the phase-two pipelines."""

    content: str = Field(description="Generated message content")
    finish_reason: str = Field(default="stop", description="stop, length, content_filter, etc.")
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    id: str = ""


class DocClassification(BaseModel):
    """Step 1: Document classification output."""

    doc_type: str = Field(description="Document type: paper, article, note, report")
    domain: str = Field(description="简体中文知识领域短标签，如 记忆管理、智能体、自然语言处理、编程")
    kind: str = Field(description="简体中文细分类别短标签，如 架构、方法、概念、工具、案例")
    topics: list[str] = Field(default_factory=list, description="Main topics")

    @model_validator(mode="after")
    def _limit_topics(self) -> "DocClassification":
        self.topics = _limit(self.topics, MAX_DOC_TOPICS)
        return self


class PathDecision(BaseModel):
    """Step 2: Path decision output."""

    source_name: str = Field(description="Proposed source note filename")
    existing_source: str | None = Field(default=None, description="Existing source to reuse")
    candidate_cards: list[str] = Field(
        default_factory=list,
        description="Proposed card names",
    )

    @model_validator(mode="after")
    def _limit_candidate_cards(self) -> "PathDecision":
        self.candidate_cards = self.candidate_cards[:STEP2_MAX_CANDIDATE_CARDS]
        return self


class SourceNoteOutput(BaseModel):
    """Step 3: Source note generation output."""

    title: str = Field(description="Source note title")
    summary: str = Field(description="Original document overview")
    extractable_knowledge_points: list[str] = Field(
        default_factory=list, description="Extractable knowledge points"
    )
    concepts: list[str] = Field(default_factory=list, description="Core concepts")

    @model_validator(mode="after")
    def _limit_outputs(self) -> "SourceNoteOutput":
        self.extractable_knowledge_points = _limit(
            self.extractable_knowledge_points,
            MAX_SOURCE_KNOWLEDGE_POINTS,
        )
        self.concepts = _limit(self.concepts, MAX_SOURCE_CONCEPTS)
        return self


class StructureSectionAnnotation(BaseModel):
    """LLM annotation for one document section."""

    section_id: int
    title: str
    content_type: str = "unknown"
    knowledge_density: str = "medium"
    contains_knowledge_cards: bool = True
    reason: str = ""


class StructureAnnotationOutput(BaseModel):
    """Phase 1 structure-aware annotation output."""

    doc_type: str = "article"
    domain: str = "general"
    main_topic: str = ""
    sections: list[StructureSectionAnnotation] = Field(default_factory=list)
    suggested_card_count: int = 0


class KnowledgePointOutput(BaseModel):
    """Phase 2 located knowledge point."""

    card_title: str
    card_type: str = "concept"
    section_id: int = 0
    para_range: list[int] = Field(default_factory=lambda: [0, 0])
    key_sentences: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    relation_to_existing: str = ""
    role: str = "concept"
    extraction_confidence: str = "medium"
    reason: str = ""


class KnowledgeMapOutput(BaseModel):
    """Phase 2 knowledge locate output (legacy, used by fast-track path)."""

    knowledge_points: list[KnowledgePointOutput] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class KnowledgePoint(BaseModel):
    """Phase 2 located knowledge point (lightweight coordinate model)."""

    name: str
    section_id: int | None = None
    section_title: str | None = None
    estimated_tokens: int = 0


class KnowledgeLocateResult(BaseModel):
    """Phase 2 knowledge location result (replaces KnowledgeMapOutput for full pipeline)."""

    knowledge_points: list[KnowledgePoint] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    total_points: int = 0
    density_map: dict[int, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_total_points(self) -> "KnowledgeLocateResult":
        if self.total_points != len(self.knowledge_points):
            self.total_points = len(self.knowledge_points)
        return self


class CardFilterResult(BaseModel):
    """Step 4: Card filtering output."""

    selected: list[str] = Field(
        default_factory=list,
        description="Knowledge points worth forming cards",
    )
    rejected: list[str] = Field(default_factory=list, description="Rejected knowledge points")
    reasons: dict[str, str] = Field(default_factory=dict, description="Rejection reasons")


class CardSection(BaseModel):
    """A content section in a generated knowledge card."""

    heading: str = Field(description="Section heading")
    content: str = Field(description="Section body")


class CardOutput(BaseModel):
    """Step 5: Single card generation output."""

    title: str = Field(description="Card title")
    summary: str = Field(description="Concise card overview")
    sections: list[CardSection] = Field(
        default_factory=list,
        description="Adaptive card body sections",
    )
    relations: str = Field(default="", description="Relations to other knowledge")
    sources_text: str = Field(default="", description="Source references in text")
    concepts: list[str] = Field(default_factory=list, description="Core concepts")
    graph_role: str = Field(default="concept", description="Graph role: concept, method")
    wikilinks: list[str] = Field(default_factory=list, description="Wikilinks to other notes")

    @model_validator(mode="after")
    def _limit_outputs(self) -> "CardOutput":
        self.concepts = _limit(self.concepts, MAX_CARD_CONCEPTS)
        self.wikilinks = _limit(self.wikilinks, MAX_CARD_WIKILINKS)
        return self


class MapOutput(BaseModel):
    """Step 6: Knowledge map generation output."""

    title: str = Field(description="Map title")
    topic_overview: str = Field(description="Topic overview")
    related_cards: list[str] = Field(default_factory=list, description="Related card paths")
    relationship_context: str = Field(default="", description="Relationship context")
    concepts: list[str] = Field(default_factory=list, description="Core concepts")
    core_concepts: list[dict] = Field(default_factory=list, description="Core concepts with roles")
    reading_path: list[dict] = Field(default_factory=list, description="Recommended reading path")
    key_relations: list[dict] = Field(default_factory=list, description="Key relations")
    source_materials: list[dict] = Field(default_factory=list, description="Source materials")
    linked_maps: list[dict] = Field(default_factory=list, description="Related map entries")

    @model_validator(mode="after")
    def _limit_outputs(self) -> "MapOutput":
        self.concepts = _limit(self.concepts, MAX_MAP_CONCEPTS)
        self.core_concepts = _limit(self.core_concepts, MAX_MAP_CORE_CONCEPTS)
        self.reading_path = _limit(self.reading_path, MAX_MAP_READING_PATH)
        self.key_relations = _limit(self.key_relations, MAX_MAP_KEY_RELATIONS)
        self.linked_maps = _limit(self.linked_maps, MAX_MAP_LINKED_MAPS)
        return self


class RelationItem(BaseModel):
    """A single relation description item."""

    source: str = Field(description="Source card or concept")
    target: str = Field(description="Target card or concept")
    relation_type: str = Field(
        description="Relation type: dependency/comparison/composition/extension",
        validation_alias=AliasChoices("relation_type", "relation", "type"),
    )
    description: str = Field(default="", description="Relation description")


class RelationDescOutput(BaseModel):
    """Step 7: Relation description output."""

    description: str = Field(description="Overall relation description for this ingestion")
    new_connections: list[RelationItem] = Field(default_factory=list, description="New connections")

    @model_validator(mode="after")
    def _limit_connections(self) -> "RelationDescOutput":
        self.new_connections = _limit(self.new_connections, MAX_RELATION_CONNECTIONS)
        return self
