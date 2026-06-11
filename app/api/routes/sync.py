"""API routes for sync and reindex."""

import logging
import time

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import ensure_instance_access, get_db, get_sync_service, require_write_context
from app.api.models import ReindexResponse, SyncResponse
from app.exceptions import InstanceNotFoundError
from app.observability import log_event

router = APIRouter(prefix="/api/v1/instances", tags=["sync"])
logger = logging.getLogger(__name__)


def _get_vault_path(instance_id: str) -> str:
    """Get vault_path for an instance from DB."""
    db = get_db()
    rows = db.execute(
        "SELECT vault_path FROM instances WHERE id = ?", (instance_id,)
    )
    if not rows:
        raise InstanceNotFoundError(f"Instance {instance_id} not found")
    return rows[0]["vault_path"]


@router.post("/{instance_id}/sync", response_model=SyncResponse)
async def sync_instance(
    instance_id: str,
    git: bool = Query(False, description="Run git pull before sync"),
    auth=Depends(require_write_context),
):
    """Sync an instance from filesystem changes.

    Pass git=true to pull from remote before syncing.
    """
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(logger, "process.sync.start", instance_id=instance_id, git=git)
    svc = get_sync_service()
    vault_path = _get_vault_path(instance_id)
    try:
        if git:
            result = svc.sync_from_git(instance_id, vault_path)
        else:
            result = svc.sync(instance_id, vault_path)
    except Exception:
        log_event(
            logger,
            "process.sync.error",
            level=logging.ERROR,
            instance_id=instance_id,
            git=git,
            duration_ms=_duration_ms(started),
            exc_info=True,
        )
        raise
    log_event(
        logger,
        "process.sync.done",
        instance_id=instance_id,
        git=git,
        added_count=len(result.added),
        modified_count=len(result.modified),
        deleted_count=len(result.deleted),
        error_count=len(result.errors),
        total_changes=result.total_changes,
        duration_ms=_duration_ms(started),
    )
    return SyncResponse(**result.to_dict())


@router.post("/{instance_id}/reindex", response_model=ReindexResponse)
async def reindex_instance(instance_id: str, auth=Depends(require_write_context)):
    """Full reindex of an instance."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    log_event(logger, "process.reindex.start", instance_id=instance_id)
    svc = get_sync_service()
    vault_path = _get_vault_path(instance_id)
    try:
        result = svc.reindex(instance_id, vault_path)
    except Exception:
        log_event(
            logger,
            "process.reindex.error",
            level=logging.ERROR,
            instance_id=instance_id,
            duration_ms=_duration_ms(started),
            exc_info=True,
        )
        raise
    log_event(
        logger,
        "process.reindex.done",
        instance_id=instance_id,
        indexed_files=result.indexed_files,
        relations_count=result.relations_count,
        concept_overlaps=result.concept_overlaps,
        error_count=len(result.errors),
        duration_ms=_duration_ms(started),
    )
    return ReindexResponse(**result.to_dict())


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
