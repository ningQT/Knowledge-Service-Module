"""API routes for instance management."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import (
    ensure_instance_access,
    get_auth_service,
    get_db,
    get_instance_service,
    require_console_context,
    require_read_context,
)
from app.api.models import (
    BoundApiKeyListResponse,
    BoundApiKeyResponse,
    CreateInstanceRequest,
    DeleteInstanceRequest,
    InstanceDeleteResponse,
    InstanceDiagnosticsResponse,
    InstanceListResponse,
    InstancePermissionAccount,
    InstancePermissionListResponse,
    InstancePermissionOwner,
    InstanceResponse,
    InstanceStatsResponse,
    UpdateInstancePermissionsRequest,
    UpdateInstanceRequest,
)
from app.core.diagnostics_service import DiagnosticsService
from app.exceptions import InstanceAlreadyExistsError
from app.observability import log_event

router = APIRouter(prefix="/api/v1/instances", tags=["instances"])
logger = logging.getLogger(__name__)


def _instance_response(instance, auth=None) -> InstanceResponse:
    data = instance.to_dict()
    data["vault_path"] = None
    owner_id = data.get("owner_account_id")
    data["owner_account_id"] = owner_id
    if auth is None:
        return InstanceResponse(**data)
    if auth.is_admin:
        access_level = "admin"
        can_edit = True
        can_manage = True
    else:
        is_owner = auth.user_id == owner_id
        permission = "edit" if is_owner else auth.permission_for(instance.id)
        access_level = "owner" if is_owner else permission
        can_edit = permission == "edit"
        can_manage = is_owner
    data.update(
        access_level=access_level,
        can_edit=can_edit,
        can_manage=can_manage,
    )
    return InstanceResponse(**data)


@router.post("", response_model=InstanceResponse, status_code=201)
async def create_instance(req: CreateInstanceRequest, auth=Depends(require_console_context)):
    """Create a new knowledge base instance."""
    started = time.perf_counter()
    log_event(
        logger,
        "instance.create.start",
        template_id=req.template_id,
        auto_map=req.auto_map,
        language=req.language,
    )
    svc = get_instance_service()
    try:
        instance = svc.create_instance(
            name=req.name,
            template_id=req.template_id,
            auto_map=req.auto_map,
            language=req.language,
            config=req.config,
            owner_account_id=auth.user_id,
        )
    except InstanceAlreadyExistsError as e:
        log_event(
            logger,
            "instance.create.error",
            level=logging.WARNING,
            reason="duplicate_name",
            duration_ms=_duration_ms(started),
        )
        raise HTTPException(status_code=409, detail=e.message) from e
    except ValueError as e:
        log_event(
            logger,
            "instance.create.error",
            level=logging.WARNING,
            reason=e.__class__.__name__,
            duration_ms=_duration_ms(started),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event(
        logger,
        "instance.create.done",
        instance_id=instance.id,
        template_id=instance.template_id,
        auto_map=instance.auto_map,
        language=instance.language,
        duration_ms=_duration_ms(started),
    )
    return _instance_response(instance, auth)


@router.get("", response_model=InstanceListResponse)
async def list_instances(auth=Depends(require_read_context)):
    """List all knowledge base instances."""
    svc = get_instance_service()
    instances = svc.list_instances()
    if not auth.is_admin:
        instances = [instance for instance in instances if instance.id in auth.instance_ids]
    return InstanceListResponse(instances=[_instance_response(i, auth) for i in instances])


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(instance_id: str, auth=Depends(require_read_context)):
    """Get a specific instance by ID."""
    ensure_instance_access(auth, instance_id)
    svc = get_instance_service()
    instance = svc.get_instance(instance_id)
    return _instance_response(instance, auth)


@router.patch("/{instance_id}", response_model=InstanceResponse)
async def update_instance(
    instance_id: str, req: UpdateInstanceRequest, auth=Depends(require_console_context)
):
    """Update editable metadata for a knowledge base instance."""
    if not get_auth_service().can_manage_instance(
        auth.user_id or "", instance_id, is_admin=auth.is_admin
    ):
        raise HTTPException(status_code=403, detail="Instance access is denied")
    started = time.perf_counter()
    log_event(
        logger,
        "instance.update.start",
        instance_id=instance_id,
        updated_fields=sorted(req.model_fields_set),
    )
    svc = get_instance_service()
    try:
        instance = svc.update_instance(
            instance_id,
            name=req.name,
            auto_map=req.auto_map,
        )
    except InstanceAlreadyExistsError as e:
        log_event(
            logger,
            "instance.update.error",
            level=logging.WARNING,
            instance_id=instance_id,
            reason="duplicate_name",
            duration_ms=_duration_ms(started),
        )
        raise HTTPException(status_code=409, detail=e.message) from e
    except ValueError as e:
        log_event(
            logger,
            "instance.update.error",
            level=logging.WARNING,
            instance_id=instance_id,
            reason=e.__class__.__name__,
            duration_ms=_duration_ms(started),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event(
        logger,
        "instance.update.done",
        instance_id=instance_id,
        auto_map=instance.auto_map,
        duration_ms=_duration_ms(started),
    )
    return _instance_response(instance, auth)


@router.delete("/{instance_id}", response_model=InstanceDeleteResponse)
async def delete_instance(
    instance_id: str,
    req: DeleteInstanceRequest,
    delete_files: bool = Query(False, description="Also delete the local vault directory"),
    auth=Depends(require_console_context),
):
    """Delete a knowledge base instance and optionally its local vault files."""
    if not get_auth_service().can_manage_instance(
        auth.user_id or "", instance_id, is_admin=auth.is_admin
    ):
        raise HTTPException(status_code=403, detail="Instance access is denied")
    instance = get_instance_service().get_instance(instance_id)
    if req.confirm_name != instance.name:
        raise HTTPException(status_code=400, detail="Instance name confirmation does not match")
    started = time.perf_counter()
    log_event(logger, "instance.delete.start", instance_id=instance_id, delete_files=delete_files)
    svc = get_instance_service()
    try:
        svc.delete_instance(instance_id, delete_files=delete_files)
    except ValueError as e:
        log_event(
            logger,
            "instance.delete.error",
            level=logging.WARNING,
            instance_id=instance_id,
            delete_files=delete_files,
            duration_ms=_duration_ms(started),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event(
        logger,
        "instance.delete.done",
        instance_id=instance_id,
        delete_files=delete_files,
        duration_ms=_duration_ms(started),
    )
    return InstanceDeleteResponse(deleted=True, id=instance_id, files_deleted=delete_files)


@router.get("/{instance_id}/permissions", response_model=InstancePermissionListResponse)
async def get_instance_permissions(
    instance_id: str,
    auth=Depends(require_console_context),
):
    """Return instance permission grants for administrators and owners."""
    try:
        data = get_auth_service().get_instance_permissions(
            instance_id,
            actor_id=auth.user_id or "",
            is_admin=auth.is_admin,
        )
    except ValueError as exc:
        status = 404 if str(exc) == "Instance not found" else 403
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return InstancePermissionListResponse(
        instance_id=data["instance_id"],
        instance_name=data["instance_name"],
        owner=InstancePermissionOwner(**data["owner"]),
        accounts=[InstancePermissionAccount(**item) for item in data["accounts"]],
    )


@router.put("/{instance_id}/permissions", response_model=InstancePermissionListResponse)
async def update_instance_permissions(
    instance_id: str,
    req: UpdateInstancePermissionsRequest,
    auth=Depends(require_console_context),
):
    """Atomically update read/edit grants for one instance."""
    try:
        data = get_auth_service().update_instance_permissions(
            instance_id,
            [item.model_dump() for item in req.permissions],
            actor_id=auth.user_id or "",
            is_admin=auth.is_admin,
        )
    except ValueError as exc:
        if str(exc) == "Instance not found":
            status = 404
        elif str(exc) == "Instance access denied":
            status = 403
        else:
            status = 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return InstancePermissionListResponse(
        instance_id=data["instance_id"],
        instance_name=data["instance_name"],
        owner=InstancePermissionOwner(**data["owner"]),
        accounts=[InstancePermissionAccount(**item) for item in data["accounts"]],
    )


@router.get("/{instance_id}/bound-api-keys", response_model=BoundApiKeyListResponse)
async def get_bound_api_keys(
    instance_id: str,
    auth=Depends(require_console_context),
):
    """Return API key summaries bound to an instance without secrets."""
    try:
        keys = get_auth_service().list_bound_api_keys(
            instance_id,
            actor_id=auth.user_id or "",
            is_admin=auth.is_admin,
        )
    except ValueError as exc:
        status = 404 if str(exc) == "Instance not found" else 403
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return BoundApiKeyListResponse(
        instance_id=instance_id,
        api_keys=[BoundApiKeyResponse(**item) for item in keys],
    )


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@router.get("/{instance_id}/stats", response_model=InstanceStatsResponse)
async def get_instance_stats(instance_id: str, auth=Depends(require_read_context)):
    """Get statistics for an instance (notes count, types, relations, etc.)."""
    db = get_db()
    ensure_instance_access(auth, instance_id)

    # Verify instance exists
    rows = db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    # Total notes
    total = db.execute("SELECT COUNT(*) AS cnt FROM notes WHERE instance_id = ?", (instance_id,))
    total_notes = total[0]["cnt"] if total else 0

    # By type
    type_rows = db.execute(
        "SELECT type, COUNT(*) AS cnt FROM notes WHERE instance_id = ? GROUP BY type",
        (instance_id,),
    )
    by_type = {r["type"]: r["cnt"] for r in type_rows if r["type"]}

    # By verification
    ver_rows = db.execute(
        "SELECT verification, COUNT(*) AS cnt FROM notes "
        "WHERE instance_id = ? GROUP BY verification",
        (instance_id,),
    )
    by_verification = {r["verification"]: r["cnt"] for r in ver_rows if r["verification"]}

    # By domain
    dom_rows = db.execute(
        "SELECT domain, COUNT(*) AS cnt FROM notes "
        "WHERE instance_id = ? AND domain IS NOT NULL GROUP BY domain",
        (instance_id,),
    )
    by_domain = {r["domain"]: r["cnt"] for r in dom_rows if r["domain"]}

    # Total relations
    rel_total = db.execute(
        "SELECT COUNT(*) AS cnt FROM relations WHERE instance_id = ?", (instance_id,)
    )
    total_relations = rel_total[0]["cnt"] if rel_total else 0

    # Last ingest time
    last_ingest = db.execute(
        "SELECT MAX(indexed_at) AS last_ts FROM notes WHERE instance_id = ?", (instance_id,)
    )
    last_ingest_at = (
        last_ingest[0]["last_ts"] if last_ingest and last_ingest[0]["last_ts"] else None
    )

    return InstanceStatsResponse(
        instance_id=instance_id,
        total_notes=total_notes,
        by_type=by_type,
        by_verification=by_verification,
        by_domain=by_domain,
        total_relations=total_relations,
        last_ingest_at=last_ingest_at,
    )


@router.get("/{instance_id}/diagnostics", response_model=InstanceDiagnosticsResponse)
async def get_instance_diagnostics(instance_id: str, auth=Depends(require_read_context)):
    """Get actionable diagnostics scoped to a single instance."""
    db = get_db()
    ensure_instance_access(auth, instance_id)
    rows = db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    return InstanceDiagnosticsResponse(**DiagnosticsService(db).get_diagnostics(instance_id))
