"""API key management routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_auth_service, require_console_context
from app.api.models import (
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    IdDeleteResponse,
    UpdateApiKeyRequest,
)

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


def _require_manage_api_key(client_id: str, account_id: str, is_admin: bool) -> None:
    try:
        allowed = get_auth_service().can_manage_api_key(
            client_id,
            account_id,
            is_admin=is_admin,
        )
    except ValueError as exc:
        status = 404 if str(exc) == "API key not found" else 403
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if not allowed:
        raise HTTPException(status_code=403, detail="API key access is not allowed")


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(auth=Depends(require_console_context)):
    """List API keys visible to the current console account."""
    keys = get_auth_service().list_api_keys(
        auth.user_id,
        include_all=auth.is_admin,
    )
    return ApiKeyListResponse(api_keys=[ApiKeyResponse(**key) for key in keys])


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(req: CreateApiKeyRequest, auth=Depends(require_console_context)):
    """Create a new API key and return the secret once."""
    try:
        key, secret = get_auth_service().create_api_key(
            req.name,
            req.scope,
            req.instance_ids,
            owner_account_id=auth.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiKeyCreateResponse(api_key=ApiKeyResponse(**key), secret=secret)


@router.patch("/{client_id}", response_model=ApiKeyResponse)
async def update_api_key(
    client_id: str,
    req: UpdateApiKeyRequest,
    auth=Depends(require_console_context),
):
    """Update API key metadata, scope, state, or instance grants."""
    try:
        key = get_auth_service().update_api_key(
            client_id,
            name=req.name,
            scope=req.scope,
            enabled=req.enabled,
            instance_ids=req.instance_ids,
            actor_id=auth.user_id,
            is_admin=auth.is_admin,
        )
    except ValueError as exc:
        if str(exc) == "API key not found":
            status = 404
        elif str(exc) == "API key access denied":
            status = 403
        else:
            status = 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return ApiKeyResponse(**key)


@router.delete("/{client_id}", response_model=IdDeleteResponse)
async def delete_api_key(client_id: str, auth=Depends(require_console_context)):
    """Delete an API key."""
    _require_manage_api_key(client_id, auth.user_id or "", auth.is_admin)
    try:
        get_auth_service().delete_api_key(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IdDeleteResponse(deleted=True, id=client_id)


@router.post("/{client_id}/rotate", response_model=ApiKeyCreateResponse)
async def rotate_api_key(client_id: str, auth=Depends(require_console_context)):
    """Rotate an API key and return the new secret once."""
    _require_manage_api_key(client_id, auth.user_id or "", auth.is_admin)
    try:
        key, secret = get_auth_service().rotate_api_key(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiKeyCreateResponse(api_key=ApiKeyResponse(**key), secret=secret)
