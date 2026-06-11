"""API routes for instance search lexicon management."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    ensure_instance_access,
    get_search_lexicon_service,
    require_read_context,
    require_write_context,
)
from app.api.models import (
    CreateSearchLexiconRequest,
    IdDeleteResponse,
    SearchLexiconEntryResponse,
    SearchLexiconListResponse,
    UpdateSearchLexiconRequest,
)
from app.core.search_lexicon_service import (
    SearchLexiconDuplicateError,
    SearchLexiconNotFoundError,
    SearchLexiconValidationError,
)
from app.observability import log_event

router = APIRouter(prefix="/api/v1/instances", tags=["search-lexicon"])
logger = logging.getLogger(__name__)


@router.get("/{instance_id}/search-lexicon", response_model=SearchLexiconListResponse)
async def list_search_lexicon(instance_id: str, auth=Depends(require_read_context)):
    """List instance-level search lexicon entries."""
    ensure_instance_access(auth, instance_id)
    svc = get_search_lexicon_service()
    try:
        entries = svc.list_entries(instance_id)
    except SearchLexiconNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SearchLexiconListResponse(
        entries=[SearchLexiconEntryResponse(**entry) for entry in entries]
    )


@router.post(
    "/{instance_id}/search-lexicon",
    response_model=SearchLexiconEntryResponse,
    status_code=201,
)
async def create_search_lexicon(
    instance_id: str,
    req: CreateSearchLexiconRequest,
    auth=Depends(require_write_context),
):
    """Create an instance-level search lexicon entry."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(
        logger,
        "search_lexicon.create.start",
        instance_id=instance_id,
        relation_type=req.relation_type,
    )
    svc = get_search_lexicon_service()
    try:
        entry = svc.create_entry(
            instance_id,
            relation_type=req.relation_type,
            canonical_term=req.canonical_term,
            variant_terms=req.variant_terms,
            enabled=req.enabled,
            notes=req.notes,
        )
    except SearchLexiconDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SearchLexiconValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SearchLexiconNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger,
        "search_lexicon.create.done",
        instance_id=instance_id,
        entry_id=entry["id"],
        duration_ms=_duration_ms(started),
    )
    return SearchLexiconEntryResponse(**entry)


@router.patch(
    "/{instance_id}/search-lexicon/{entry_id}",
    response_model=SearchLexiconEntryResponse,
)
async def update_search_lexicon(
    instance_id: str,
    entry_id: str,
    req: UpdateSearchLexiconRequest,
    auth=Depends(require_write_context),
):
    """Update an instance-level search lexicon entry."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field")
    svc = get_search_lexicon_service()
    try:
        entry = svc.update_entry(instance_id, entry_id, updates)
    except SearchLexiconDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SearchLexiconValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SearchLexiconNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger,
        "search_lexicon.update.done",
        instance_id=instance_id,
        entry_id=entry_id,
        updated_fields=sorted(updates),
        duration_ms=_duration_ms(started),
    )
    return SearchLexiconEntryResponse(**entry)


@router.delete("/{instance_id}/search-lexicon/{entry_id}", response_model=IdDeleteResponse)
async def delete_search_lexicon(
    instance_id: str,
    entry_id: str,
    auth=Depends(require_write_context),
):
    """Delete an instance-level search lexicon entry."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    svc = get_search_lexicon_service()
    try:
        svc.delete_entry(instance_id, entry_id)
    except SearchLexiconNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log_event(
        logger,
        "search_lexicon.delete.done",
        instance_id=instance_id,
        entry_id=entry_id,
        duration_ms=_duration_ms(started),
    )
    return IdDeleteResponse(deleted=True, id=entry_id)


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
