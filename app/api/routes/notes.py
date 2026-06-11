"""API routes for note access."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import ensure_instance_access, get_note_service, require_read_context, require_write_context
from app.api.models import (
    NoteDeleteResponse,
    NoteFacetsResponse,
    NoteListResponse,
    NoteResponse,
    UpdateNoteMetadataRequest,
    UpdateNoteVerificationRequest,
)
from app.exceptions import InstanceNotFoundError
from app.observability import log_event
from app.storage.path_utils import UnsafePathError, validate_vault_relative_path

router = APIRouter(prefix="/api/v1/instances", tags=["notes"])
logger = logging.getLogger(__name__)

USER_SETTABLE_VERIFICATIONS = {"verified", "unverified", "draft"}


@router.get("/{instance_id}/notes", response_model=NoteListResponse)
async def list_notes(
    instance_id: str,
    type: str | None = Query(None, description="Filter by note type"),
    domain: str | None = Query(None, description="Filter by domain"),
    kind: str | None = Query(None, description="Filter by kind"),
    graph_layer: int | None = Query(None, description="Filter by graph layer"),
    verification: str | None = Query(None, description="Filter by review status"),
    q: str | None = Query(None, description="Search title, path, or concepts"),
    auth=Depends(require_read_context),
):
    """List notes in an instance with optional filters."""
    ensure_instance_access(auth, instance_id)
    svc = get_note_service()
    try:
        notes = svc.list_notes(
            instance_id=instance_id,
            note_type=type,
            domain=domain,
            kind=kind,
            graph_layer=graph_layer,
            verification=verification,
            query=q,
        )
        return NoteListResponse(notes=notes)
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{instance_id}/notes/facets", response_model=NoteFacetsResponse)
async def list_note_facets(instance_id: str, auth=Depends(require_read_context)):
    """List normalized metadata facets for an instance."""
    ensure_instance_access(auth, instance_id)
    svc = get_note_service()
    try:
        return NoteFacetsResponse(facets=svc.list_facets(instance_id))
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{instance_id}/notes/{path:path}", response_model=NoteResponse)
async def get_note(instance_id: str, path: str, auth=Depends(require_read_context)):
    """Get a specific note by path."""
    ensure_instance_access(auth, instance_id)
    try:
        path = validate_vault_relative_path(path)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail="Invalid vault path") from e
    svc = get_note_service()
    try:
        note = svc.get_note(instance_id, path)
        if not note:
            raise HTTPException(status_code=404, detail=f"Note {path} not found")
        return NoteResponse(**note.to_dict())
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{instance_id}/notes/{path:path}/verification", response_model=NoteResponse)
async def update_note_verification(
    instance_id: str,
    path: str,
    req: UpdateNoteVerificationRequest,
    auth=Depends(require_write_context),
):
    """Update a note's manual review status."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    if req.verification not in USER_SETTABLE_VERIFICATIONS:
        raise HTTPException(status_code=400, detail="Invalid note verification status")

    try:
        path = validate_vault_relative_path(path)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail="Invalid vault path") from e
    log_event(
        logger,
        "note.verification.update.start",
        instance_id=instance_id,
        path=path,
        verification=req.verification,
    )
    svc = get_note_service()
    try:
        note = svc.update_verification(instance_id, path, req.verification)
        if not note:
            raise HTTPException(status_code=404, detail=f"Note {path} not found")
        log_event(
            logger,
            "note.verification.update.done",
            instance_id=instance_id,
            path=path,
            verification=req.verification,
            duration_ms=_duration_ms(started),
        )
        return NoteResponse(**note.to_dict())
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{instance_id}/notes/{path:path}/metadata", response_model=NoteResponse)
async def update_note_metadata(
    instance_id: str,
    path: str,
    req: UpdateNoteMetadataRequest,
    auth=Depends(require_write_context),
):
    """Update editable note metadata frontmatter fields."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    updates = {
        field: getattr(req, field)
        for field in req.model_fields_set
        if field in {"domain", "kind", "verification"}
    }
    if "verification" in updates and updates["verification"] not in USER_SETTABLE_VERIFICATIONS:
        raise HTTPException(status_code=400, detail="Invalid note verification status")

    try:
        path = validate_vault_relative_path(path)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail="Invalid vault path") from e
    log_event(
        logger,
        "note.metadata.update.start",
        instance_id=instance_id,
        path=path,
        updated_fields=sorted(updates),
    )
    svc = get_note_service()
    try:
        note = svc.update_metadata(instance_id, path, updates)
        if not note:
            raise HTTPException(status_code=404, detail=f"Note {path} not found")
        log_event(
            logger,
            "note.metadata.update.done",
            instance_id=instance_id,
            path=path,
            updated_fields=sorted(updates),
            duration_ms=_duration_ms(started),
        )
        return NoteResponse(**note.to_dict())
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{instance_id}/notes/{path:path}", response_model=NoteDeleteResponse)
async def delete_note(instance_id: str, path: str, auth=Depends(require_write_context)):
    """Delete a note file and remove its indexed data."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    try:
        path = validate_vault_relative_path(path)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail="Invalid vault path") from e
    log_event(logger, "note.delete.start", instance_id=instance_id, path=path)
    svc = get_note_service()
    try:
        deleted = svc.delete_note(instance_id, path)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Note {path} not found")
        log_event(
            logger,
            "note.delete.done",
            instance_id=instance_id,
            path=path,
            duration_ms=_duration_ms(started),
        )
        return NoteDeleteResponse(deleted=True, path=path)
    except InstanceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
