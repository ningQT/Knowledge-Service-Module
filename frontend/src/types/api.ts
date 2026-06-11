// Backend API response types

export type { GraphNode, GraphEdge, GraphData } from './graph'

export interface Instance {
  id: string
  name: string
  template_id: string
  vault_path: string | null
  auto_map: boolean
  language: 'zh' | 'en'
  created_at: string
  updated_at: string
}

export interface AuthUser {
  id: string
  username: string
  created_at?: string | null
  updated_at?: string | null
}

export interface AuthStatus {
  setup_required: boolean
  authenticated: boolean
  user: AuthUser | null
}

export interface AuthResponse {
  authenticated: boolean
  user: AuthUser
}

export interface ApiKeyClient {
  id: string
  name: string
  key_prefix: string
  scope: 'read' | 'write'
  enabled: boolean
  instance_ids: string[]
  created_at: string
  updated_at: string
  last_used_at: string | null
}

export interface ApiKeyCreateResponse {
  api_key: ApiKeyClient
  secret: string
}

export interface InstanceStats {
  instance_id: string
  total_notes: number
  by_type: Record<string, number>
  by_verification: Record<string, number>
  by_domain: Record<string, number>
  total_relations: number
  last_ingest_at: string | null
}

export interface DiagnosticIssue {
  code: string
  severity: 'info' | 'warning' | 'error' | string
  title: string
  message: string
  file_path: string | null
  details: Record<string, unknown>
}

export interface InstanceDiagnostics {
  instance_id: string
  summary: {
    total_notes: number
    issue_count: number
    unresolved_links: number
    isolated_nodes: number
    missing_sources: number
    field_warnings: number
    weak_maps: number
    unreviewed_ratio: number
  }
  issues: DiagnosticIssue[]
}

export interface IngestStep {
  step: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  summary?: Record<string, unknown>
}

export interface IngestJob {
  job_id: string
  instance_id: string
  status: string
  steps: IngestStep[]
  created_files: string[]
  generated_cards: string[]
  generated_maps: string[]
  warnings: string[]
  started_at: string | null
  finished_at: string | null
}

export interface CancelJobResponse {
  cancelled: boolean
  message: string
}

export interface SseTokenResponse {
  sse_token: string
  expires_at: string
  sse_url: string
}

export interface LLMSettings {
  provider: string
  provider_display_name: string | null
  base_url: string
  api_key_masked: string
  model: string
  temperature: number
  max_tokens: number
  configured: boolean
  missing_fields: string[]
  provider_options: LLMProviderOption[]
}

export interface LLMProviderOption {
  id: string
  display_name: string
  docs_url: string
  default_base_url: string | null
  model_examples: string[]
  required_fields: string[]
  capabilities: string[]
}

export interface LLMTestResult {
  success: boolean
  model: string
  latency_ms: number | null
  error: string | null
}

export interface SearchStats {
  core_count: number
  related_count: number
  source_count: number
  map_count: number
  total: number
  fallback_mode: boolean
  search_path: string
  map_sourced_count: number
}

export interface SearchNode {
  instance_id: string
  path: string
  title: string
  graph_layer: number
  domain?: string | null
  kind?: string | null
  verification?: string
  score?: number
  match_type?: string
  hop_distance?: number | null
  rel_type_to_anchor?: string | null
  [key: string]: unknown
}

export interface SearchResult {
  query: string
  intent_type: string
  query_context: {
    concept_candidates?: string[]
    exact_candidates?: string[]
    phrase_candidates?: string[]
    expanded_candidates?: string[]
    domain_hint?: string | null
    matched_facets?: Record<string, unknown>[]
  }
  core_hits: SearchNode[]
  related_cards: SearchNode[]
  source_notes: SearchNode[]
  maps: SearchNode[]
  map_priority: boolean
  key_relations: Record<string, unknown>[]
  stats: SearchStats
  comprehension: Record<string, unknown> | null
}

export type SearchLexiconRelationType = 'alias' | 'synonym'

export interface SearchLexiconEntry {
  id: string
  instance_id: string
  relation_type: SearchLexiconRelationType
  canonical_term: string
  variant_terms: string[]
  enabled: boolean
  notes: string
  created_at: string
  updated_at: string
}

export interface SearchLexiconListResponse {
  entries: SearchLexiconEntry[]
}

export interface CreateSearchLexiconRequest {
  relation_type: SearchLexiconRelationType
  canonical_term: string
  variant_terms: string[]
  enabled: boolean
  notes?: string
}

export interface UpdateSearchLexiconRequest {
  relation_type?: SearchLexiconRelationType
  canonical_term?: string
  variant_terms?: string[]
  enabled?: boolean
  notes?: string
}

export interface EvidenceCard {
  path: string
  title: string
  source_note_paths: string[]
  map_paths: string[]
  relation_chain: string[]
  summary: string
}

export interface AnswerCitation {
  id: string
  source_note_path: string | null
  source_title: string
  evidence_cards: string[]
  relation_chain: string[]
  traced: boolean
  note: string
}

export interface ProcessSummary {
  step: string
  title: string
  summary: string
  details: Record<string, unknown>
}

export interface BatchProcessCard {
  path: string
  title: string
  citation_ids?: string[]
  key_points?: string[]
}

export interface LLMTokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export interface BatchProcessDetail {
  batch_id: string
  status?: 'processing' | 'completed' | 'failed' | string
  card_count?: number
  cards?: BatchProcessCard[]
  summary?: string
  key_points?: string[]
  citation_ids?: string[]
  fallback?: boolean
  used_for_synthesis?: boolean
  error?: string | null
  elapsed_ms?: number
  token_usage?: LLMTokenUsage | null
  model?: string
}

export interface CardSummary {
  card_path: string
  title: string
  relevance_to_query: string
  key_points: string[]
  source_citation_ids: string[]
  conflicts_or_limits: string[]
}

export interface BatchSummary {
  batch_id: string
  card_paths: string[]
  summary: string
  key_points: string[]
  citation_ids: string[]
}

export interface TopicSummary {
  topic: string
  batch_ids: string[]
  card_paths: string[]
  summary: string
  key_points: string[]
  citation_ids: string[]
}

export interface AnswerSection {
  id: string
  title: string
  summary: string
  content_md?: string
  key_points: string[]
  citations: string[]
  batch_ids: string[]
  card_paths: string[]
  coverage_status: 'covered' | 'partial' | 'untraced' | string
  remaining_card_count: number
  expandable: boolean
  continuation_hint: string
}

export interface CoverageLedger {
  maps_found: number
  cards_found: number
  cards_read: number
  cards_summarized: number
  cards_used_for_synthesis: number
  cards_skipped_by_budget: number
  summary_batches_total: number
  summary_batches_used: number
  summary_batches_failed: number
  citations_total: number
  citations_traced: number
  citations_untraced: number
}

export interface AnswerResult {
  query: string
  answer: string
  answer_md?: string
  key_points: string[]
  citations: AnswerCitation[]
  evidence_cards: EvidenceCard[]
  process_summaries: ProcessSummary[]
  coverage_ledger: CoverageLedger
  batch_summaries: BatchSummary[]
  topic_summaries: TopicSummary[]
  sections: AnswerSection[]
  search_result: SearchResult | null
  comprehension: Record<string, unknown> | null
  warnings: string[]
}

export interface AnswerStep {
  step: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  summary?: Record<string, unknown> | null
}

export interface AnswerJob {
  job_id: string
  status: string
  query: string
  steps: AnswerStep[]
  result: AnswerResult | null
  warnings: string[]
  started_at: string | null
  finished_at: string | null
}

// =============================================================================
// Ontology types
// =============================================================================

export type OntologyRelationType = 'is_a' | 'has_role' | 'part_of' | 'related_to' | 'caused_by' | 'influenced_by'
export type OntologyEntityStatus = 'active' | 'candidate' | 'deprecated'
export type OntologyEvidenceType = 'mention' | 'quote' | 'inference'

export interface OntologyType {
  id: string
  instance_id: string
  name: string
  description: string
  parent_type_id: string | null
  status: string
  searchable: boolean
  source: string
  confidence: number
  created_at: string
  updated_at: string
}

export interface OntologyEntity {
  id: string
  instance_id: string
  name: string
  entity_type_id: string | null
  description: string
  status: string
  searchable: boolean
  source: string
  confidence: number
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface OntologyAlias {
  id: string
  instance_id: string
  entity_id: string
  alias_text: string
  source: string
  created_at: string
}

export interface OntologyRelation {
  id: string
  instance_id: string
  source_entity_id: string
  target_entity_id: string
  source_entity?: OntologyEntity | null
  target_entity?: OntologyEntity | null
  relation_type: string
  description: string
  status: string
  searchable: boolean
  source: string
  confidence: number
  created_at: string
  updated_at: string
}

export interface OntologyEvidence {
  id: string
  instance_id: string
  relation_id: string
  file_path: string
  evidence_type: string
  snippet: string
  confidence: number
  status: string
  created_at: string
}

export interface OntologyTypeListResponse {
  types: OntologyType[]
}

export interface OntologyEntityListResponse {
  entities: OntologyEntity[]
}

export interface OntologyRelationListResponse {
  relations: OntologyRelation[]
}

export interface OntologyAliasListResponse {
  aliases: OntologyAlias[]
}

export interface OntologyEvidenceListResponse {
  evidence: OntologyEvidence[]
}

export interface CreateOntologyTypeRequest {
  name: string
  description?: string
  parent_type_id?: string
  source?: string
  confidence?: number
}

export interface UpdateOntologyTypeRequest {
  name?: string
  description?: string
  parent_type_id?: string
  status?: string
  searchable?: boolean
  confidence?: number
}

export interface CreateOntologyEntityRequest {
  name: string
  entity_type_id?: string | null
  description?: string
  source?: string
  confidence?: number
  metadata?: Record<string, unknown>
}

export interface UpdateOntologyEntityRequest {
  name?: string
  entity_type_id?: string | null
  description?: string
  status?: string
  searchable?: boolean
  confidence?: number
  metadata?: Record<string, unknown>
}

export interface CreateOntologyRelationRequest {
  source_entity_id: string
  target_entity_id: string
  relation_type: OntologyRelationType
  description?: string
  source?: string
  confidence?: number
}

export interface UpdateOntologyRelationRequest {
  description?: string
  status?: string
  searchable?: boolean
  confidence?: number
}

export interface CreateOntologyAliasRequest {
  alias_text: string
  source?: string
}

export interface CreateOntologyEvidenceRequest {
  file_path: string
  evidence_type?: string
  snippet?: string
  confidence?: number
}

export interface BatchStatusUpdateRequest {
  ids: string[]
  status: string
}

export interface BatchStatusUpdateResponse {
  updated: number
  not_found: string[]
}

export interface OntologyStatusCounts {
  active: number
  candidate: number
  deprecated: number
}

export interface OntologyCacheInfo {
  cached: boolean
  instance_id: string
  built_at?: string | null
}

export interface OntologyStatsResponse {
  types: OntologyStatusCounts
  entities: OntologyStatusCounts
  relations: OntologyStatusCounts
  cache: OntologyCacheInfo
}

export interface OntologySwitchStatusResponse {
  global_enabled: boolean
  instance_enabled: boolean
  cache: OntologyCacheInfo
}
