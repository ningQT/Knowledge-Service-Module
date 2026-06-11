"""API request/response models for all endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


# === Auth endpoints ===

class AdminUserResponse(BaseModel):
    id: str
    username: str
    created_at: str | None = None
    updated_at: str | None = None


class AuthStatusResponse(BaseModel):
    setup_required: bool
    authenticated: bool = False
    user: AdminUserResponse | None = None


class AdminSetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AuthResponse(BaseModel):
    authenticated: bool = True
    user: AdminUserResponse


class LogoutResponse(BaseModel):
    logged_out: bool = True


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scope: str
    enabled: bool
    instance_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    last_used_at: str | None = None


class ApiKeyListResponse(BaseModel):
    api_keys: list[ApiKeyResponse] = Field(default_factory=list)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = "read"
    instance_ids: list[str] = Field(default_factory=list, max_length=200)


class UpdateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    scope: str | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    instance_ids: list[str] | None = Field(default=None, max_length=200)


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyResponse
    secret: str

# === Instance endpoints ===

class CreateInstanceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_id: str = Field(default="standard_v1", max_length=80)
    auto_map: bool = True
    language: Literal["zh", "en"] = "zh"
    config: dict = Field(default_factory=dict)


class UpdateInstanceRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    auto_map: bool | None = None


class InstanceResponse(BaseModel):
    id: str
    name: str
    template_id: str
    vault_path: str | None = None
    auto_map: bool
    language: Literal["zh", "en"] = "zh"
    created_at: str
    updated_at: str


class InstanceListResponse(BaseModel):
    instances: list[InstanceResponse]


# === Ingest endpoint ===

class IngestResponse(BaseModel):
    job_id: str
    status: str
    created_files: list[str] = Field(default_factory=list)
    generated_cards: list[str] = Field(default_factory=list)
    generated_maps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# === Search endpoint ===

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    instance_ids: list[str] | None = Field(default=None, max_length=200)
    layer_filter: int | None = None       # 1=资料来源, 2=知识卡片, 3=知识地图
    verification_filter: str | None = None # "verified" / "unverified" / "draft"
    include_comprehension: bool = True


class SearchNodeResponse(BaseModel):
    path: str
    title: str
    graph_layer: int = 0
    domain: str | None = None
    kind: str | None = None
    verification: str = "unverified"
    score: float = 0.0
    match_type: str = ""
    hop_distance: int | None = None
    rel_type_to_anchor: str | None = None


class SearchStatsResponse(BaseModel):
    core_count: int = 0
    related_count: int = 0
    source_count: int = 0
    map_count: int = 0
    total: int = 0
    fallback_mode: bool = False
    search_path: str = "card_scatter"
    map_sourced_count: int = 0


class SearchResponse(BaseModel):
    query: str
    intent_type: str
    query_context: dict = Field(default_factory=dict)
    core_hits: list[dict] = Field(default_factory=list)
    related_cards: list[dict] = Field(default_factory=list)
    source_notes: list[dict] = Field(default_factory=list)
    maps: list[dict] = Field(default_factory=list)
    map_priority: bool = False
    key_relations: list[dict] = Field(default_factory=list)
    stats: SearchStatsResponse = Field(default_factory=SearchStatsResponse)
    comprehension: dict | None = None


class AnswerOptionsRequest(BaseModel):
    strategy: str = Field(default="map_card_first", max_length=40)
    citation_level: str = Field(default="source_note", max_length=40)


class SearchAnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    instance_ids: list[str] | None = Field(default=None, max_length=200)
    include_search_result: bool = False
    include_comprehension: bool = False
    answer_options: AnswerOptionsRequest = Field(default_factory=AnswerOptionsRequest)


class SearchAnswerJobResponse(BaseModel):
    job_id: str
    status: str = "pending"


class SearchAnswerJobStatusResponse(BaseModel):
    job_id: str
    status: str
    query: str
    steps: list[dict] = Field(default_factory=list)
    result: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None


class SseTokenResponse(BaseModel):
    sse_token: str
    expires_at: str
    sse_url: str


# === Search lexicon endpoints ===

class SearchLexiconEntryResponse(BaseModel):
    id: str
    instance_id: str
    relation_type: Literal["alias", "synonym"]
    canonical_term: str
    variant_terms: list[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str = ""
    created_at: str
    updated_at: str


class SearchLexiconListResponse(BaseModel):
    entries: list[SearchLexiconEntryResponse] = Field(default_factory=list)


class CreateSearchLexiconRequest(BaseModel):
    relation_type: Literal["alias", "synonym"]
    canonical_term: str = Field(min_length=1, max_length=120)
    variant_terms: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=1000)


class UpdateSearchLexiconRequest(BaseModel):
    relation_type: Literal["alias", "synonym"] | None = None
    canonical_term: str | None = Field(default=None, max_length=120)
    variant_terms: list[str] | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


# === Sync endpoints ===

class SyncResponse(BaseModel):
    added: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    total_changes: int = 0


class ReindexResponse(BaseModel):
    indexed_files: int = 0
    relations_count: int = 0
    concept_overlaps: int = 0
    errors: list[str] = Field(default_factory=list)


# === Note endpoint ===

class NoteResponse(BaseModel):
    file_path: str
    title: str
    type: str
    domain: str | None = None
    kind: str | None = None
    graph_layer: int = 0
    graph_role: str | None = None
    verification: str = "unverified"
    status: str = "active"
    frontmatter: dict = Field(default_factory=dict)
    body: str = ""


class NoteListResponse(BaseModel):
    notes: list[dict] = Field(default_factory=list)


class NoteFacetsResponse(BaseModel):
    facets: dict[str, list[str]] = Field(default_factory=dict)


class UpdateNoteVerificationRequest(BaseModel):
    verification: str = Field(max_length=40)


class UpdateNoteMetadataRequest(BaseModel):
    domain: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, max_length=120)
    verification: str | None = Field(default=None, max_length=40)


class IdDeleteResponse(BaseModel):
    deleted: bool = True
    id: str
    path: str | None = None


class NoteDeleteResponse(BaseModel):
    deleted: bool = True
    id: str | None = None
    path: str


class InstanceDeleteResponse(BaseModel):
    deleted: bool = True
    id: str
    path: str | None = None
    files_deleted: bool = False


# === Error response ===

class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str | None = None


# === Phase 3: Instance stats ===

class InstanceStatsResponse(BaseModel):
    instance_id: str
    total_notes: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_verification: dict[str, int] = Field(default_factory=dict)
    by_domain: dict[str, int] = Field(default_factory=dict)
    total_relations: int = 0
    last_ingest_at: str | None = None


class DiagnosticIssueResponse(BaseModel):
    code: str
    severity: str = "info"
    title: str
    message: str
    file_path: str | None = None
    details: dict = Field(default_factory=dict)


class InstanceDiagnosticsResponse(BaseModel):
    instance_id: str
    summary: dict = Field(default_factory=dict)
    issues: list[DiagnosticIssueResponse] = Field(default_factory=list)


# === Phase 3: Graph API ===

class GraphNodeResponse(BaseModel):
    id: str
    title: str
    type: str
    graph_layer: int
    graph_role: str | None = None
    verification: str = "unverified"
    domain: str | None = None
    concepts: list[str] = Field(default_factory=list)
    unresolved: bool = False
    target_text: str | None = None


class GraphEdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    rel_type: str
    source_field: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNodeResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


# === Phase 3: Async ingest + SSE ===

class AsyncIngestResponse(BaseModel):
    job_id: str
    status: str = "pending"


class CancelJobResponse(BaseModel):
    cancelled: bool = True
    message: str = ""


class IngestJobResponse(BaseModel):
    job_id: str
    instance_id: str
    status: str
    steps: list[dict] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    generated_cards: list[str] = Field(default_factory=list)
    generated_maps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None


# === Phase 3: LLM Settings ===

class LLMSettingsRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class LLMProviderOption(BaseModel):
    id: str
    display_name: str
    docs_url: str
    default_base_url: str | None = None
    model_examples: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class LLMSettingsResponse(BaseModel):
    provider: str
    provider_display_name: str | None = None
    base_url: str
    api_key_masked: str
    model: str
    temperature: float
    max_tokens: int
    configured: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    provider_options: list[LLMProviderOption] = Field(default_factory=list)


class LLMSettingsUpdateResponse(BaseModel):
    updated: bool = True
    settings: LLMSettingsResponse


class LLMSettingsResetResponse(BaseModel):
    reset: bool = True
    message: str = "LLM configuration cleared."


class LLMTestRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class LLMTestResponse(BaseModel):
    success: bool
    model: str
    latency_ms: int | None = None
    error: str | None = None


# === Ontology endpoints (Phase 8) ===

class OntologyTypeResponse(BaseModel):
    id: str
    instance_id: str
    name: str
    description: str = ""
    parent_type_id: str | None = None
    status: str = "active"
    searchable: bool = True
    source: str = "manual"
    confidence: float = 1.0
    created_at: str
    updated_at: str


class OntologyTypeListResponse(BaseModel):
    types: list[OntologyTypeResponse] = Field(default_factory=list)


class CreateOntologyTypeRequest(BaseModel):
    name: str
    description: str = ""
    parent_type_id: str | None = None
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UpdateOntologyTypeRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_type_id: str | None = None
    status: Literal["active", "candidate", "deprecated"] | None = None
    searchable: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OntologyEntityResponse(BaseModel):
    id: str
    instance_id: str
    name: str
    entity_type_id: str | None = None
    description: str = ""
    status: str = "active"
    searchable: bool = True
    source: str = "manual"
    confidence: float = 1.0
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class OntologyEntityListResponse(BaseModel):
    entities: list[OntologyEntityResponse] = Field(default_factory=list)


class CreateOntologyEntityRequest(BaseModel):
    name: str
    entity_type_id: str | None = None
    description: str = ""
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


class UpdateOntologyEntityRequest(BaseModel):
    name: str | None = None
    entity_type_id: str | None = None
    description: str | None = None
    status: Literal["active", "candidate", "deprecated"] | None = None
    searchable: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict | None = None


class OntologyAliasResponse(BaseModel):
    id: str
    instance_id: str
    entity_id: str
    alias_text: str
    source: str = "manual"
    created_at: str


class OntologyAliasListResponse(BaseModel):
    aliases: list[OntologyAliasResponse] = Field(default_factory=list)


class CreateOntologyAliasRequest(BaseModel):
    alias_text: str
    source: str = "manual"


class OntologyRelationResponse(BaseModel):
    id: str
    instance_id: str
    source_entity_id: str
    target_entity_id: str
    source_entity: OntologyEntityResponse | None = None
    target_entity: OntologyEntityResponse | None = None
    relation_type: str
    description: str = ""
    status: str = "active"
    searchable: bool = True
    source: str = "manual"
    confidence: float = 1.0
    created_at: str
    updated_at: str


class OntologyRelationListResponse(BaseModel):
    relations: list[OntologyRelationResponse] = Field(default_factory=list)


class CreateOntologyRelationRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    description: str = ""
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UpdateOntologyRelationRequest(BaseModel):
    description: str | None = None
    status: Literal["active", "candidate", "deprecated"] | None = None
    searchable: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OntologyEvidenceResponse(BaseModel):
    id: str
    instance_id: str
    relation_id: str
    file_path: str
    evidence_type: str = "mention"
    snippet: str = ""
    confidence: float = 1.0
    status: str = "active"
    created_at: str


class OntologyEvidenceListResponse(BaseModel):
    evidence: list[OntologyEvidenceResponse] = Field(default_factory=list)


class CreateOntologyEvidenceRequest(BaseModel):
    file_path: str
    evidence_type: str = "mention"
    snippet: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OntologyEntityLinkResponse(BaseModel):
    id: str
    instance_id: str
    entity_id: str
    file_path: str
    link_type: str = "mention"
    snippet: str = ""
    confidence: float = 1.0
    status: str = "active"
    created_at: str


class OntologyEntityLinkListResponse(BaseModel):
    links: list[OntologyEntityLinkResponse] = Field(default_factory=list)


class BatchStatusUpdateRequest(BaseModel):
    ids: list[str]
    status: Literal["active", "candidate", "deprecated"]


class BatchStatusUpdateResponse(BaseModel):
    updated: int
    not_found: list[str] = Field(default_factory=list)


class OntologyStatusCounts(BaseModel):
    active: int = 0
    candidate: int = 0
    deprecated: int = 0


class OntologyCacheInfo(BaseModel):
    cached: bool
    instance_id: str
    built_at: str | None = None


class OntologyStatsResponse(BaseModel):
    types: OntologyStatusCounts
    entities: OntologyStatusCounts
    relations: OntologyStatusCounts
    cache: OntologyCacheInfo


class OntologySwitchStatusResponse(BaseModel):
    global_enabled: bool
    instance_enabled: bool
    cache: OntologyCacheInfo
