"""API routes for instance ontology management."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    ensure_instance_access,
    get_db,
    get_ontology_service,
    require_read_context,
    require_write_context,
)
from app.api.models import (
    BatchStatusUpdateRequest,
    BatchStatusUpdateResponse,
    CreateOntologyAliasRequest,
    CreateOntologyEntityRequest,
    CreateOntologyEvidenceRequest,
    CreateOntologyRelationRequest,
    CreateOntologyTypeRequest,
    IdDeleteResponse,
    OntologyAliasListResponse,
    OntologyAliasResponse,
    OntologyCacheInfo,
    OntologyEntityLinkListResponse,
    OntologyEntityLinkResponse,
    OntologyEntityListResponse,
    OntologyEntityResponse,
    OntologyEvidenceListResponse,
    OntologyEvidenceResponse,
    OntologyRelationListResponse,
    OntologyRelationResponse,
    OntologyStatsResponse,
    OntologyStatusCounts,
    OntologySwitchStatusResponse,
    OntologyTypeListResponse,
    OntologyTypeResponse,
    UpdateOntologyEntityRequest,
    UpdateOntologyRelationRequest,
    UpdateOntologyTypeRequest,
)
from app.core.ontology_service import (
    OntologyDuplicateError,
    OntologyNotFoundError,
    OntologyValidationError,
)
from app.observability import log_event

router = APIRouter(prefix="/api/v1/instances", tags=["ontology"])
logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


@router.get("/{instance_id}/ontology/types", response_model=OntologyTypeListResponse)
async def list_ontology_types(
    instance_id: str,
    status: str | None = None,
    source: str | None = None,
    auth=Depends(require_read_context),
):
    """List ontology types for an instance."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        types = svc.list_types(instance_id, status=status, source=source)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyTypeListResponse(
        types=[OntologyTypeResponse(**t) for t in types]
    )


@router.post(
    "/{instance_id}/ontology/types",
    response_model=OntologyTypeResponse,
    status_code=201,
)
async def create_ontology_type(
    instance_id: str,
    req: CreateOntologyTypeRequest,
    auth=Depends(require_write_context),
):
    """Create an ontology type."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(logger, "ontology.type.create.start", instance_id=instance_id, name=req.name)
    svc = get_ontology_service()
    try:
        type_data = svc.create_type(
            instance_id,
            name=req.name,
            description=req.description,
            parent_type_id=req.parent_type_id,
            source=req.source,
            confidence=req.confidence,
        )
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.type.create.done",
        instance_id=instance_id, type_id=type_data["id"],
        duration_ms=_duration_ms(started),
    )
    return OntologyTypeResponse(**type_data)


@router.patch(
    "/{instance_id}/ontology/types/{type_id}",
    response_model=OntologyTypeResponse,
)
async def update_ontology_type(
    instance_id: str,
    type_id: str,
    req: UpdateOntologyTypeRequest,
    auth=Depends(require_write_context),
):
    """Update an ontology type."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field")
    svc = get_ontology_service()
    try:
        type_data = svc.update_type(instance_id, type_id, updates)
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.type.update.done",
        instance_id=instance_id, type_id=type_id,
        duration_ms=_duration_ms(started),
    )
    return OntologyTypeResponse(**type_data)


@router.delete(
    "/{instance_id}/ontology/types/{type_id}",
    response_model=IdDeleteResponse,
)
async def delete_ontology_type(
    instance_id: str,
    type_id: str,
    auth=Depends(require_write_context),
):
    """Delete an ontology type."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        svc.delete_type(instance_id, type_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(logger, "ontology.type.delete.done", instance_id=instance_id, type_id=type_id)
    return IdDeleteResponse(deleted=True, id=type_id)


# =============================================================================
# Entities
# =============================================================================


@router.get("/{instance_id}/ontology/entities", response_model=OntologyEntityListResponse)
async def list_ontology_entities(
    instance_id: str,
    type_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    auth=Depends(require_read_context),
):
    """List ontology entities, optionally filtered by type, status, or source."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        entities = svc.list_entities(instance_id, type_id=type_id, status=status, source=source)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyEntityListResponse(
        entities=[OntologyEntityResponse(**e) for e in entities]
    )


@router.post(
    "/{instance_id}/ontology/entities",
    response_model=OntologyEntityResponse,
    status_code=201,
)
async def create_ontology_entity(
    instance_id: str,
    req: CreateOntologyEntityRequest,
    auth=Depends(require_write_context),
):
    """Create an ontology entity."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(logger, "ontology.entity.create.start", instance_id=instance_id, name=req.name)
    svc = get_ontology_service()
    try:
        entity = svc.create_entity(
            instance_id,
            name=req.name,
            entity_type_id=req.entity_type_id,
            description=req.description,
            source=req.source,
            confidence=req.confidence,
            metadata=req.metadata,
        )
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.entity.create.done",
        instance_id=instance_id, entity_id=entity["id"],
        duration_ms=_duration_ms(started),
    )
    return OntologyEntityResponse(**entity)


@router.patch(
    "/{instance_id}/ontology/entities/{entity_id}",
    response_model=OntologyEntityResponse,
)
async def update_ontology_entity(
    instance_id: str,
    entity_id: str,
    req: UpdateOntologyEntityRequest,
    auth=Depends(require_write_context),
):
    """Update an ontology entity."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field")
    svc = get_ontology_service()
    try:
        entity = svc.update_entity(instance_id, entity_id, updates)
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.entity.update.done",
        instance_id=instance_id, entity_id=entity_id,
        duration_ms=_duration_ms(started),
    )
    return OntologyEntityResponse(**entity)


@router.delete(
    "/{instance_id}/ontology/entities/{entity_id}",
    response_model=IdDeleteResponse,
)
async def delete_ontology_entity(
    instance_id: str,
    entity_id: str,
    auth=Depends(require_write_context),
):
    """Delete an ontology entity."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        svc.delete_entity(instance_id, entity_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(logger, "ontology.entity.delete.done", instance_id=instance_id, entity_id=entity_id)
    return IdDeleteResponse(deleted=True, id=entity_id)


# =============================================================================
# Aliases
# =============================================================================


@router.get(
    "/{instance_id}/ontology/entities/{entity_id}/aliases",
    response_model=OntologyAliasListResponse,
)
async def list_entity_aliases(
    instance_id: str,
    entity_id: str,
    auth=Depends(require_read_context),
):
    """List aliases for an ontology entity."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        aliases = svc.list_aliases(instance_id, entity_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyAliasListResponse(
        aliases=[OntologyAliasResponse(**a) for a in aliases]
    )


@router.post(
    "/{instance_id}/ontology/entities/{entity_id}/aliases",
    response_model=OntologyAliasResponse,
    status_code=201,
)
async def create_entity_alias(
    instance_id: str,
    entity_id: str,
    req: CreateOntologyAliasRequest,
    auth=Depends(require_write_context),
):
    """Add an alias to an ontology entity."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        alias = svc.add_alias(instance_id, entity_id, req.alias_text, req.source)
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        svc.auto_bridge_entity(instance_id, entity_id, extra_terms=[req.alias_text])
    except Exception:
        logger.warning("Auto-bridge after alias creation failed for entity %s", entity_id, exc_info=True)
    return OntologyAliasResponse(**alias)


@router.delete(
    "/{instance_id}/ontology/entities/{entity_id}/aliases/{alias_id}",
    response_model=IdDeleteResponse,
)
async def delete_entity_alias(
    instance_id: str,
    entity_id: str,
    alias_id: str,
    auth=Depends(require_write_context),
):
    """Delete an alias from an ontology entity."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        svc.delete_alias(instance_id, alias_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return IdDeleteResponse(deleted=True, id=alias_id)


# =============================================================================
# Entity-Note Links
# =============================================================================


@router.get(
    "/{instance_id}/ontology/entities/{entity_id}/links",
    response_model=OntologyEntityLinkListResponse,
)
async def list_entity_links(
    instance_id: str,
    entity_id: str,
    auth=Depends(require_read_context),
):
    """List document links for an ontology entity."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        links = svc.list_entity_links(instance_id, entity_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyEntityLinkListResponse(
        links=[OntologyEntityLinkResponse(**link) for link in links]
    )


# =============================================================================
# Relations
# =============================================================================


@router.get("/{instance_id}/ontology/relations", response_model=OntologyRelationListResponse)
async def list_ontology_relations(
    instance_id: str,
    entity_id: str | None = None,
    relation_type: str | None = None,
    status: str | None = None,
    source: str | None = None,
    auth=Depends(require_read_context),
):
    """List ontology relations, optionally filtered by entity, type, status, or source."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        relations = svc.list_relations(instance_id, entity_id=entity_id, relation_type=relation_type, status=status, source=source)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyRelationListResponse(
        relations=[OntologyRelationResponse(**r) for r in relations]
    )


@router.post(
    "/{instance_id}/ontology/relations",
    response_model=OntologyRelationResponse,
    status_code=201,
)
async def create_ontology_relation(
    instance_id: str,
    req: CreateOntologyRelationRequest,
    auth=Depends(require_write_context),
):
    """Create an ontology relation."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(
        logger, "ontology.relation.create.start",
        instance_id=instance_id,
        source=req.source_entity_id, target=req.target_entity_id,
    )
    svc = get_ontology_service()
    try:
        relation = svc.create_relation(
            instance_id,
            source_entity_id=req.source_entity_id,
            target_entity_id=req.target_entity_id,
            relation_type=req.relation_type,
            description=req.description,
            source=req.source,
            confidence=req.confidence,
        )
    except OntologyDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.relation.create.done",
        instance_id=instance_id, relation_id=relation["id"],
        duration_ms=_duration_ms(started),
    )
    return OntologyRelationResponse(**relation)


@router.patch(
    "/{instance_id}/ontology/relations/{relation_id}",
    response_model=OntologyRelationResponse,
)
async def update_ontology_relation(
    instance_id: str,
    relation_id: str,
    req: UpdateOntologyRelationRequest,
    auth=Depends(require_write_context),
):
    """Update an ontology relation."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field")
    svc = get_ontology_service()
    try:
        relation = svc.update_relation(instance_id, relation_id, updates)
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger, "ontology.relation.update.done",
        instance_id=instance_id, relation_id=relation_id,
        duration_ms=_duration_ms(started),
    )
    return OntologyRelationResponse(**relation)


@router.delete(
    "/{instance_id}/ontology/relations/{relation_id}",
    response_model=IdDeleteResponse,
)
async def delete_ontology_relation(
    instance_id: str,
    relation_id: str,
    auth=Depends(require_write_context),
):
    """Delete an ontology relation."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        svc.delete_relation(instance_id, relation_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(logger, "ontology.relation.delete.done", instance_id=instance_id, relation_id=relation_id)
    return IdDeleteResponse(deleted=True, id=relation_id)


# =============================================================================
# Evidence
# =============================================================================


@router.get(
    "/{instance_id}/ontology/relations/{relation_id}/evidence",
    response_model=OntologyEvidenceListResponse,
)
async def list_relation_evidence(
    instance_id: str,
    relation_id: str,
    auth=Depends(require_read_context),
):
    """List evidence for an ontology relation."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()
    try:
        evidence = svc.list_evidence(instance_id, relation_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyEvidenceListResponse(
        evidence=[OntologyEvidenceResponse(**e) for e in evidence]
    )


@router.post(
    "/{instance_id}/ontology/relations/{relation_id}/evidence",
    response_model=OntologyEvidenceResponse,
    status_code=201,
)
async def create_relation_evidence(
    instance_id: str,
    relation_id: str,
    req: CreateOntologyEvidenceRequest,
    auth=Depends(require_write_context),
):
    """Add evidence to an ontology relation."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        evidence = svc.add_evidence(
            instance_id,
            relation_id,
            file_path=req.file_path,
            evidence_type=req.evidence_type,
            snippet=req.snippet,
            confidence=req.confidence,
        )
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return OntologyEvidenceResponse(**evidence)


# =============================================================================
# Batch operations
# =============================================================================


@router.post(
    "/{instance_id}/ontology/entities/batch-status",
    response_model=BatchStatusUpdateResponse,
)
async def batch_update_entity_status(
    instance_id: str,
    req: BatchStatusUpdateRequest,
    auth=Depends(require_write_context),
):
    """Batch update status for ontology entities."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        result = svc.batch_update_status(instance_id, "entity", req.ids, req.status)
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return BatchStatusUpdateResponse(**result)


@router.post(
    "/{instance_id}/ontology/relations/batch-status",
    response_model=BatchStatusUpdateResponse,
)
async def batch_update_relation_status(
    instance_id: str,
    req: BatchStatusUpdateRequest,
    auth=Depends(require_write_context),
):
    """Batch update status for ontology relations."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        result = svc.batch_update_status(instance_id, "relation", req.ids, req.status)
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return BatchStatusUpdateResponse(**result)


@router.post(
    "/{instance_id}/ontology/types/batch-status",
    response_model=BatchStatusUpdateResponse,
)
async def batch_update_type_status(
    instance_id: str,
    req: BatchStatusUpdateRequest,
    auth=Depends(require_write_context),
):
    """Batch update status for ontology types."""
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_ontology_service()
    try:
        result = svc.batch_update_status(instance_id, "type", req.ids, req.status)
    except OntologyValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return BatchStatusUpdateResponse(**result)


# =============================================================================
# Stats
# =============================================================================


@router.get(
    "/{instance_id}/ontology/stats",
    response_model=OntologyStatsResponse,
)
async def get_ontology_stats(
    instance_id: str,
    auth=Depends(require_read_context),
):
    """Get ontology statistics for an instance."""
    ensure_instance_access(auth, instance_id)
    svc = get_ontology_service()

    def _count_by_status(items: list[dict]) -> OntologyStatusCounts:
        counts = OntologyStatusCounts()
        for item in items:
            s = item.get("status", "active")
            if hasattr(counts, s):
                setattr(counts, s, getattr(counts, s) + 1)
        return counts

    try:
        types = svc.list_types(instance_id)
        entities = svc.list_entities(instance_id)
        relations = svc.list_relations(instance_id)
    except OntologyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    from app.core.ontology_cache import _cache as ontology_cache_dict
    cached_data = ontology_cache_dict.get(instance_id)
    cache_info = OntologyCacheInfo(
        cached=cached_data is not None,
        instance_id=instance_id,
        built_at=getattr(cached_data, "built_at", None) if cached_data else None,
    )

    return OntologyStatsResponse(
        types=_count_by_status(types),
        entities=_count_by_status(entities),
        relations=_count_by_status(relations),
        cache=cache_info,
    )


# =============================================================================
# Switch management
# =============================================================================


@router.get(
    "/{instance_id}/ontology/switch-status",
    response_model=OntologySwitchStatusResponse,
)
async def get_ontology_switch_status(
    instance_id: str,
    auth=Depends(require_read_context),
):
    """Get ontology switch status for an instance."""
    ensure_instance_access(auth, instance_id)

    # Global switch
    db = get_ontology_service().db
    global_enabled = False
    rows = db.execute("SELECT value FROM settings WHERE key = 'ontology.enabled'")
    if rows:
        global_enabled = rows[0]["value"] == "1"

    # Instance switch
    instance_enabled = False
    rows = db.execute("SELECT config_json FROM instances WHERE id = ?", (instance_id,))
    if rows:
        import json
        try:
            config = json.loads(rows[0].get("config_json", "{}")) if isinstance(rows[0].get("config_json"), str) else {}
        except (json.JSONDecodeError, TypeError):
            config = {}
        instance_enabled = bool(config.get("ontology_enabled", True))

    from app.core.ontology_cache import _cache as ontology_cache_dict
    cached_data = ontology_cache_dict.get(instance_id)
    cache_info = OntologyCacheInfo(
        cached=cached_data is not None,
        instance_id=instance_id,
        built_at=getattr(cached_data, "built_at", None) if cached_data else None,
    )

    return OntologySwitchStatusResponse(
        global_enabled=global_enabled,
        instance_enabled=instance_enabled,
        cache=cache_info,
    )


@router.post(
    "/{instance_id}/ontology/enable",
)
async def enable_ontology_for_instance(
    instance_id: str,
    auth=Depends(require_write_context),
):
    """Enable ontology for a specific instance."""
    ensure_instance_access(auth, instance_id, write=True)
    db = get_ontology_service().db
    _set_instance_ontology_switch(db, instance_id, True)
    return {"enabled": True, "instance_id": instance_id}


@router.post(
    "/{instance_id}/ontology/disable",
)
async def disable_ontology_for_instance(
    instance_id: str,
    auth=Depends(require_write_context),
):
    """Disable ontology for a specific instance."""
    ensure_instance_access(auth, instance_id, write=True)
    db = get_ontology_service().db
    _set_instance_ontology_switch(db, instance_id, False)
    return {"enabled": False, "instance_id": instance_id}


def _set_instance_ontology_switch(db, instance_id: str, enabled: bool) -> None:
    """Update the ontology_enabled field in instance config_json."""
    import json
    from datetime import UTC, datetime

    rows = db.execute("SELECT config_json FROM instances WHERE id = ?", (instance_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        config = json.loads(rows[0].get("config_json", "{}")) if isinstance(rows[0].get("config_json"), str) else rows[0].get("config_json") or {}
    except (json.JSONDecodeError, TypeError):
        config = {}

    config["ontology_enabled"] = enabled
    now = datetime.now(UTC).isoformat()
    db.execute(
        "UPDATE instances SET config_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(config, ensure_ascii=False), now, instance_id),
    )


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
