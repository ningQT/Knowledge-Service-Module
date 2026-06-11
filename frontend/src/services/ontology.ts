import api from './client'
import type {
  BatchStatusUpdateRequest,
  BatchStatusUpdateResponse,
  CreateOntologyAliasRequest,
  CreateOntologyEntityRequest,
  CreateOntologyEvidenceRequest,
  CreateOntologyRelationRequest,
  CreateOntologyTypeRequest,
  OntologyAlias,
  OntologyAliasListResponse,
  OntologyEntity,
  OntologyEntityListResponse,
  OntologyEvidence,
  OntologyEvidenceListResponse,
  OntologyRelation,
  OntologyRelationListResponse,
  OntologyStatsResponse,
  OntologySwitchStatusResponse,
  OntologyType,
  OntologyTypeListResponse,
  UpdateOntologyEntityRequest,
  UpdateOntologyRelationRequest,
  UpdateOntologyTypeRequest,
} from '@/types/api'

// --- Types ---

export async function listOntologyTypes(instanceId: string, options?: { status?: string; source?: string }): Promise<OntologyType[]> {
  const params = new URLSearchParams()
  if (options?.status) params.set('status', options.status)
  if (options?.source) params.set('source', options.source)
  const qs = params.toString()
  const data = await api.get(`instances/${instanceId}/ontology/types${qs ? `?${qs}` : ''}`).json<OntologyTypeListResponse>()
  return data.types
}

export async function createOntologyType(
  instanceId: string,
  data: CreateOntologyTypeRequest,
): Promise<OntologyType> {
  return api.post(`instances/${instanceId}/ontology/types`, { json: data }).json<OntologyType>()
}

export async function updateOntologyType(
  instanceId: string,
  typeId: string,
  data: UpdateOntologyTypeRequest,
): Promise<OntologyType> {
  return api.patch(`instances/${instanceId}/ontology/types/${typeId}`, { json: data }).json<OntologyType>()
}

export async function deleteOntologyType(
  instanceId: string,
  typeId: string,
): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`instances/${instanceId}/ontology/types/${typeId}`).json<{ deleted: boolean; id: string }>()
}

// --- Entities ---

export async function listOntologyEntities(
  instanceId: string,
  typeId?: string,
  options?: { status?: string; source?: string },
): Promise<OntologyEntity[]> {
  const params = new URLSearchParams()
  if (typeId) params.set('type_id', typeId)
  if (options?.status) params.set('status', options.status)
  if (options?.source) params.set('source', options.source)
  const qs = params.toString()
  const data = await api.get(`instances/${instanceId}/ontology/entities${qs ? `?${qs}` : ''}`).json<OntologyEntityListResponse>()
  return data.entities
}

export async function createOntologyEntity(
  instanceId: string,
  data: CreateOntologyEntityRequest,
): Promise<OntologyEntity> {
  return api.post(`instances/${instanceId}/ontology/entities`, { json: data }).json<OntologyEntity>()
}

export async function updateOntologyEntity(
  instanceId: string,
  entityId: string,
  data: UpdateOntologyEntityRequest,
): Promise<OntologyEntity> {
  return api.patch(`instances/${instanceId}/ontology/entities/${entityId}`, { json: data }).json<OntologyEntity>()
}

export async function deleteOntologyEntity(
  instanceId: string,
  entityId: string,
): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`instances/${instanceId}/ontology/entities/${entityId}`).json<{ deleted: boolean; id: string }>()
}

// --- Aliases (sub-resource of entities) ---

export async function listOntologyAliases(
  instanceId: string,
  entityId: string,
): Promise<OntologyAlias[]> {
  const data = await api.get(`instances/${instanceId}/ontology/entities/${entityId}/aliases`).json<OntologyAliasListResponse>()
  return data.aliases
}

export async function createOntologyAlias(
  instanceId: string,
  entityId: string,
  data: CreateOntologyAliasRequest,
): Promise<OntologyAlias> {
  return api.post(`instances/${instanceId}/ontology/entities/${entityId}/aliases`, { json: data }).json<OntologyAlias>()
}

export async function deleteOntologyAlias(
  instanceId: string,
  entityId: string,
  aliasId: string,
): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`instances/${instanceId}/ontology/entities/${entityId}/aliases/${aliasId}`).json<{ deleted: boolean; id: string }>()
}

// --- Relations ---

export async function listOntologyRelations(
  instanceId: string,
  entityId?: string,
  relationType?: string,
  options?: { status?: string; source?: string },
): Promise<OntologyRelation[]> {
  const params = new URLSearchParams()
  if (entityId) params.set('entity_id', entityId)
  if (relationType) params.set('relation_type', relationType)
  if (options?.status) params.set('status', options.status)
  if (options?.source) params.set('source', options.source)
  const qs = params.toString()
  const data = await api.get(`instances/${instanceId}/ontology/relations${qs ? `?${qs}` : ''}`).json<OntologyRelationListResponse>()
  return data.relations
}

export async function createOntologyRelation(
  instanceId: string,
  data: CreateOntologyRelationRequest,
): Promise<OntologyRelation> {
  return api.post(`instances/${instanceId}/ontology/relations`, { json: data }).json<OntologyRelation>()
}

export async function updateOntologyRelation(
  instanceId: string,
  relationId: string,
  data: UpdateOntologyRelationRequest,
): Promise<OntologyRelation> {
  return api.patch(`instances/${instanceId}/ontology/relations/${relationId}`, { json: data }).json<OntologyRelation>()
}

export async function deleteOntologyRelation(
  instanceId: string,
  relationId: string,
): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`instances/${instanceId}/ontology/relations/${relationId}`).json<{ deleted: boolean; id: string }>()
}

// --- Evidence (sub-resource of relations) ---

export async function listOntologyEvidence(
  instanceId: string,
  relationId: string,
): Promise<OntologyEvidence[]> {
  const data = await api.get(`instances/${instanceId}/ontology/relations/${relationId}/evidence`).json<OntologyEvidenceListResponse>()
  return data.evidence
}

export async function createOntologyEvidence(
  instanceId: string,
  relationId: string,
  data: CreateOntologyEvidenceRequest,
): Promise<OntologyEvidence> {
  return api.post(`instances/${instanceId}/ontology/relations/${relationId}/evidence`, { json: data }).json<OntologyEvidence>()
}

// --- Batch operations ---

export async function batchUpdateEntityStatus(
  instanceId: string,
  data: BatchStatusUpdateRequest,
): Promise<BatchStatusUpdateResponse> {
  return api.post(`instances/${instanceId}/ontology/entities/batch-status`, { json: data }).json<BatchStatusUpdateResponse>()
}

export async function batchUpdateRelationStatus(
  instanceId: string,
  data: BatchStatusUpdateRequest,
): Promise<BatchStatusUpdateResponse> {
  return api.post(`instances/${instanceId}/ontology/relations/batch-status`, { json: data }).json<BatchStatusUpdateResponse>()
}

export async function batchUpdateTypeStatus(
  instanceId: string,
  data: BatchStatusUpdateRequest,
): Promise<BatchStatusUpdateResponse> {
  return api.post(`instances/${instanceId}/ontology/types/batch-status`, { json: data }).json<BatchStatusUpdateResponse>()
}

// --- Stats ---

export async function getOntologyStats(instanceId: string): Promise<OntologyStatsResponse> {
  return api.get(`instances/${instanceId}/ontology/stats`).json<OntologyStatsResponse>()
}

// --- Switch management ---

export async function getOntologySwitchStatus(instanceId: string): Promise<OntologySwitchStatusResponse> {
  return api.get(`instances/${instanceId}/ontology/switch-status`).json<OntologySwitchStatusResponse>()
}

export async function enableOntology(instanceId: string): Promise<{ enabled: boolean; instance_id: string }> {
  return api.post(`instances/${instanceId}/ontology/enable`).json<{ enabled: boolean; instance_id: string }>()
}

export async function disableOntology(instanceId: string): Promise<{ enabled: boolean; instance_id: string }> {
  return api.post(`instances/${instanceId}/ontology/disable`).json<{ enabled: boolean; instance_id: string }>()
}
